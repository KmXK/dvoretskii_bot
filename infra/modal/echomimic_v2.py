"""
EchoMimicV2 deployment on Modal.

Usage:
    modal run modal_echomimic.py::main \\
        --photo ~/Desktop/photo.jpg \\
        --audio news_avatar/test_audio.wav \\
        --output news_avatar/out.mp4

First run will:
  1. Build image (~5-10 min, one-time)
  2. Download ~20 GB of weights from HuggingFace into a Modal Volume (~5-10 min)
  3. Run inference (~3-6 min on L4 for 8 sec video)

Subsequent runs reuse image and weights; cold start ~10-30 sec, inference 3-6 min.
"""
import os
from pathlib import Path

import modal

APP_NAME = "echomimic-v2"
VOLUME_NAME = "echomimic-weights"

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04",
        add_python="3.10",
    )
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0", "libsm6", "libxext6")
    .pip_install(
        "torch==2.4.1",
        "torchvision==0.19.1",
        index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install("setuptools<70", "wheel", "pip>=24")
    .run_commands(
        "git clone https://github.com/antgroup/echomimic_v2.git /app",
        # CLIP's setup.py imports pkg_resources at top — pip's isolated build env
        # doesn't have setuptools, so install it with --no-build-isolation
        "pip install --no-build-isolation 'clip @ https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip'",
        "cd /app && grep -v '^clip @' requirements.txt > requirements_no_clip.txt && pip install -r requirements_no_clip.txt",
    )
    .pip_install("huggingface_hub==0.26.2")
    .env({"PYTHONPATH": "/app", "FFMPEG_PATH": "/usr/bin"})
)

app = modal.App(APP_NAME, image=image)
weights_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.cls(
    gpu="L4",
    volumes={"/weights": weights_volume},
    timeout=1200,
    scaledown_window=120,
)
class EchoMimicV2:
    @modal.enter()
    def setup(self):
        import sys
        import torch
        from omegaconf import OmegaConf

        sys.path.insert(0, "/app")
        os.chdir("/app")

        weights_dir = Path("/weights/pretrained_weights")
        weights_dir.mkdir(parents=True, exist_ok=True)
        from huggingface_hub import snapshot_download

        # 1. Main EchoMimicV2 weights (denoising/reference unet, motion, pose, audio_processor)
        if not (weights_dir / "denoising_unet_acc.pth").exists():
            print("[setup] Downloading main EchoMimicV2 weights...")
            snapshot_download(
                repo_id="BadToBest/EchoMimicV2",
                local_dir=str(weights_dir),
                max_workers=8,
            )

        # 2. sd-vae-ft-mse (VAE)
        if not (weights_dir / "sd-vae-ft-mse" / "config.json").exists():
            print("[setup] Downloading sd-vae-ft-mse...")
            snapshot_download(
                repo_id="stabilityai/sd-vae-ft-mse",
                local_dir=str(weights_dir / "sd-vae-ft-mse"),
                max_workers=4,
            )

        # 3. sd-image-variations-diffusers (base UNet)
        if not (weights_dir / "sd-image-variations-diffusers" / "unet" / "config.json").exists():
            print("[setup] Downloading sd-image-variations-diffusers...")
            snapshot_download(
                repo_id="lambdalabs/sd-image-variations-diffusers",
                local_dir=str(weights_dir / "sd-image-variations-diffusers"),
                max_workers=4,
            )

        # 4. whisper tiny (audio model)
        whisper_dir = weights_dir / "audio_processor"
        whisper_dir.mkdir(parents=True, exist_ok=True)
        tiny_pt = whisper_dir / "tiny.pt"
        if not tiny_pt.exists():
            import urllib.request
            url = "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt"
            print(f"[setup] Downloading whisper tiny.pt from {url}")
            urllib.request.urlretrieve(url, str(tiny_pt))

        weights_volume.commit()
        print("[setup] All weights present and committed to volume")

        repo_weights = Path("/app/pretrained_weights")
        if not repo_weights.exists():
            os.symlink(weights_dir, repo_weights)

        from diffusers import AutoencoderKL, DDIMScheduler
        from src.models.unet_2d_condition import UNet2DConditionModel
        from src.models.unet_3d_emo import EMOUNet3DConditionModel
        from src.models.whisper.audio2feature import load_audio_model
        from src.models.pose_encoder import PoseEncoder
        from src.pipelines.pipeline_echomimicv2_acc import EchoMimicV2Pipeline

        config = OmegaConf.load("/app/configs/prompts/infer_acc.yaml")
        infer_config = OmegaConf.load(config.inference_config)
        weight_dtype = torch.float16
        device = "cuda"

        print("[setup] Loading VAE...")
        vae = AutoencoderKL.from_pretrained(config.pretrained_vae_path).to(
            device, dtype=weight_dtype
        )

        print("[setup] Loading reference unet...")
        reference_unet = UNet2DConditionModel.from_pretrained(
            config.pretrained_base_model_path, subfolder="unet"
        ).to(dtype=weight_dtype, device=device)
        reference_unet.load_state_dict(
            torch.load(config.reference_unet_path, map_location="cpu")
        )

        print("[setup] Loading denoising unet...")
        denoising_unet = EMOUNet3DConditionModel.from_pretrained_2d(
            config.pretrained_base_model_path,
            config.motion_module_path,
            subfolder="unet",
            unet_additional_kwargs=infer_config.unet_additional_kwargs,
        ).to(dtype=weight_dtype, device=device)
        denoising_unet.load_state_dict(
            torch.load(config.denoising_unet_path, map_location="cpu"), strict=False
        )

        print("[setup] Loading pose encoder...")
        pose_net = PoseEncoder(
            320, conditioning_channels=3, block_out_channels=(16, 32, 96, 256)
        ).to(dtype=weight_dtype, device=device)
        pose_net.load_state_dict(torch.load(config.pose_encoder_path))

        print("[setup] Loading audio processor...")
        audio_processor = load_audio_model(
            model_path=config.audio_model_path, device=device
        )

        sched_kwargs = OmegaConf.to_container(infer_config.noise_scheduler_kwargs)
        scheduler = DDIMScheduler(**sched_kwargs)

        self.pipe = EchoMimicV2Pipeline(
            vae=vae,
            reference_unet=reference_unet,
            denoising_unet=denoising_unet,
            audio_guider=audio_processor,
            pose_encoder=pose_net,
            scheduler=scheduler,
        ).to(device, dtype=weight_dtype)

        self.weight_dtype = weight_dtype
        self.device = device
        print("[setup] Ready")

    @modal.method()
    def infer(
        self,
        image_bytes: bytes,
        audio_bytes: bytes,
        pose_name: str = "01",
        width: int = 768,
        height: int = 768,
        steps: int = 6,
        cfg: float = 1.0,
        fps: int = 24,
        seed: int = 420,
    ) -> bytes:
        import tempfile
        import numpy as np
        import torch
        from PIL import Image
        from src.utils.dwpose_util import draw_pose_select_v2
        from src.utils.util import save_videos_grid
        from moviepy.editor import VideoFileClip, AudioFileClip

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            img_path = tdp / "ref.png"
            aud_path = tdp / "audio.wav"
            img_path.write_bytes(image_bytes)
            aud_path.write_bytes(audio_bytes)

            pose_dir = Path(f"/app/assets/halfbody_demo/pose/{pose_name}")
            if not pose_dir.exists():
                raise ValueError(f"Pose template '{pose_name}' not found at {pose_dir}")

            ref_img = Image.open(img_path).convert("RGB").resize((width, height))
            audio_clip = AudioFileClip(str(aud_path))

            pose_frames_avail = len([p for p in pose_dir.iterdir() if p.suffix == ".npy"])
            L = int(audio_clip.duration * fps)
            print(f"[infer] audio={audio_clip.duration:.2f}s, pose_frames={pose_frames_avail}, L={L} (pose loops as needed)")

            pose_list = []
            for index in range(0, L):
                pose_idx = index % pose_frames_avail
                tgt_musk = np.zeros((width, height, 3)).astype("uint8")
                pose_data = np.load(
                    pose_dir / f"{pose_idx}.npy", allow_pickle=True
                ).tolist()
                imh_new, imw_new, rb, re, cb, ce = pose_data["draw_pose_params"]
                im = draw_pose_select_v2(pose_data, imh_new, imw_new, ref_w=800)
                im = np.transpose(np.array(im), (1, 2, 0))
                tgt_musk[rb:re, cb:ce, :] = im
                tgt_musk_pil = Image.fromarray(np.array(tgt_musk)).convert("RGB")
                pose_list.append(
                    torch.Tensor(np.array(tgt_musk_pil))
                    .to(dtype=self.weight_dtype, device=self.device)
                    .permute(2, 0, 1)
                    / 255.0
                )

            poses_tensor = torch.stack(pose_list, dim=1).unsqueeze(0)
            audio_clip = audio_clip.set_duration(L / fps)
            generator = torch.manual_seed(seed)

            print(f"[infer] Running pipeline: {width}x{height}, {L} frames, {steps} steps...")
            video = self.pipe(
                ref_img,
                str(aud_path),
                poses_tensor[:, :, :L, ...],
                width,
                height,
                L,
                steps,
                cfg,
                generator=generator,
                audio_sample_rate=16000,
                context_frames=12,
                fps=fps,
                context_overlap=3,
                start_idx=0,
            ).videos

            final_length = min(video.shape[2], poses_tensor.shape[2], L)
            video_sig = video[:, :, :final_length, :, :]

            silent = tdp / "silent.mp4"
            save_videos_grid(video_sig, str(silent), n_rows=1, fps=fps)

            final = tdp / "out.mp4"
            VideoFileClip(str(silent)).set_audio(audio_clip).write_videofile(
                str(final),
                codec="libx264",
                audio_codec="aac",
                threads=2,
                logger=None,
            )

            return final.read_bytes()


@app.local_entrypoint()
def main(
    photo: str,
    audio: str,
    output: str = "out.mp4",
    pose: str = "01",
    steps: int = 6,
    cfg: float = 1.0,
    width: int = 768,
    height: int = 768,
    seed: int = 420,
):
    img = Path(photo).expanduser().read_bytes()
    aud = Path(audio).expanduser().read_bytes()
    print(
        f"-> Sending {len(img)//1024} KB image, {len(aud)//1024} KB audio "
        f"(pose={pose}, steps={steps}, cfg={cfg}, {width}x{height}, seed={seed})"
    )
    video = EchoMimicV2().infer.remote(
        img, aud, pose_name=pose, steps=steps, cfg=cfg,
        width=width, height=height, seed=seed,
    )
    out_path = Path(output).expanduser()
    out_path.write_bytes(video)
    print(f"<- Saved {len(video)//1024} KB video to {out_path}")
