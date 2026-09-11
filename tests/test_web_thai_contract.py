from pathlib import Path


def test_web_dashboard_contains_thai_localized_labels():
    source = (Path(__file__).parents[1] / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    for label in ("แดชบอร์ด", "สแกนเนอร์", "การตั้งค่า", "โหมดจำลอง", "คะแนน", "ราคา", "คำเตือน"):
        assert label in source
