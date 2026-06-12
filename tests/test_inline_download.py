from steward.features.download.yt import find_download_urls


def test_finds_short_tiktok_link():
    assert find_download_urls("глянь https://vt.tiktok.com/ZS2abc/ ага") == [
        ("https://vt.tiktok.com/ZS2abc/", "tiktok"),
    ]


def test_finds_full_tiktok_link():
    assert find_download_urls("https://www.tiktok.com/@user/video/7234567890") == [
        ("https://www.tiktok.com/@user/video/7234567890", "tiktok"),
    ]


def test_finds_instagram_link():
    assert find_download_urls("https://www.instagram.com/reel/DZPPR8pNuup/") == [
        ("https://www.instagram.com/reel/DZPPR8pNuup/", "instagram.com"),
    ]


def test_finds_all_supported_hosts():
    text = (
        "https://youtu.be/abc https://youtube.com/watch?v=1 "
        "https://pin.it/xyz https://ru.pinterest.com/pin/1/ "
        "https://music.yandex.ru/track/1"
    )
    assert [key for _, key in find_download_urls(text)] == [
        "youtu.be",
        "youtube.com",
        "pin.it",
        "pinterest.com",
        "music.yandex",
    ]


def test_ignores_lookalike_host():
    assert find_download_urls("https://nottiktok.example.com/x") == []
    assert find_download_urls("https://example.com/tiktok") == []
    assert find_download_urls("https://myinstagram.com.evil.io/x") == []


def test_ignores_plain_text():
    assert find_download_urls("просто текст без ссылок") == []
    assert find_download_urls("") == []


def test_finds_multiple_urls_in_text():
    text = "вот https://vm.tiktok.com/XYZ/ и ещё https://www.instagram.com/p/AbC/"
    assert find_download_urls(text) == [
        ("https://vm.tiktok.com/XYZ/", "tiktok"),
        ("https://www.instagram.com/p/AbC/", "instagram.com"),
    ]
