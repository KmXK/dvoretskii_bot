from steward.bot.inline_download import find_tiktok_url


def test_finds_short_link():
    assert (
        find_tiktok_url("глянь https://vt.tiktok.com/ZS2abc/ ага")
        == "https://vt.tiktok.com/ZS2abc/"
    )


def test_finds_full_link():
    assert (
        find_tiktok_url("https://www.tiktok.com/@user/video/7234567890")
        == "https://www.tiktok.com/@user/video/7234567890"
    )


def test_ignores_lookalike_host():
    assert find_tiktok_url("https://nottiktok.example.com/x") is None
    assert find_tiktok_url("https://example.com/tiktok") is None


def test_ignores_plain_text():
    assert find_tiktok_url("просто текст без ссылок") is None
    assert find_tiktok_url("") is None


def test_picks_tiktok_among_other_urls():
    text = "https://youtube.com/watch?v=1 и https://vm.tiktok.com/XYZ/"
    assert find_tiktok_url(text) == "https://vm.tiktok.com/XYZ/"
