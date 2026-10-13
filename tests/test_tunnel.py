from pathlib import Path

from scripts.tunnel import latest_tunnel_url


def test_real_free_tunnel_rotation_output_selects_latest_url():
    observed = Path(__file__).resolve().parents[1] / "docs" / "observed-tunnel-rotation.log"
    content = observed.read_text(encoding="utf-8")
    assert latest_tunnel_url(content.split("c7f5fc55ec4608.lhr.life tunneled")[0]) is None
    assert latest_tunnel_url(content) == "https://58945690b46def.lhr.life"
