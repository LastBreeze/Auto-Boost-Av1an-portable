from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "Auto-Boost-Av1an.py"


def test_ffvship_failure_uses_vs_hip_fallback_message():
    text = SOURCE.read_text(encoding="utf-8")
    assert "FFVship failed, using vs-hip fallback" in text


def test_ffvship_failure_does_not_immediately_exit_before_fallback():
    text = SOURCE.read_text(encoding="utf-8")
    fallback_message_at = text.index("FFVship failed, using vs-hip fallback")
    old_direct_exit = 'console.print(f"[red]FFVship failed: {e}[/red]")\n                    raise SystemExit(1)'
    if old_direct_exit in text:
        assert text.index(old_direct_exit) > fallback_message_at


def test_ffvship_fallback_uses_existing_vship_calculation_path():
    text = SOURCE.read_text(encoding="utf-8")
    assert "_activate_vship_plugin" in text
    assert "_calculate_ssimu2_vship" in text
    assert "FFVship failed, using vs-hip fallback" in text
