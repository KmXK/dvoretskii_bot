from steward.bot.inline_download import find_supported_url


def test_finds_short_tiktok_link():
    assert find_supported_url("глянь https://vt.tiktok.com/ZS2abc/ ага") == (
        "https://vt.tiktok.com/ZS2abc/",
        "tiktok",
    )


def test_finds_full_tiktok_link():
    assert find_supported_url("https://www.tiktok.com/@user/video/7234567890") == (
        "https://www.tiktok.com/@user/video/7234567890",
        "tiktok",
    )


def test_finds_instagram_link():
    assert find_supported_url("https://www.instagram.com/reel/DZPPR8pNuup/") == (
        "https://www.instagram.com/reel/DZPPR8pNuup/",
        "instagram",
    )


def test_ignores_lookalike_host():
    assert find_supported_url("https://nottiktok.example.com/x") is None
    assert find_supported_url("https://example.com/tiktok") is None
    assert find_supported_url("https://myinstagram.com.evil.io/x") is None


def test_ignores_plain_text():
    assert find_supported_url("просто текст без ссылок") is None
    assert find_supported_url("") is None


def test_picks_supported_among_other_urls():
    text = "https://youtube.com/watch?v=1 и https://vm.tiktok.com/XYZ/"
    assert find_supported_url(text) == ("https://vm.tiktok.com/XYZ/", "tiktok")
