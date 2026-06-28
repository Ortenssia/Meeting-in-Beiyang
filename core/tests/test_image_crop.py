from PIL import Image

from core.frontend.image_crop import CropState, render_crop


def test_crop_state_starts_centered_and_never_exposes_empty_space():
    state = CropState(1200, 800, 300, 300)

    assert state.display_height == 300
    assert state.x == -75
    assert state.y == 0

    state.pan(10_000, -10_000)
    assert state.x == 0
    assert state.y == state.viewport_height - state.display_height


def test_zoom_keeps_the_same_source_point_at_viewport_center():
    state = CropState(1600, 900, 336, 112)
    before = tuple((value / state.source_width if index % 2 == 0 else value / state.source_height)
                   for index, value in enumerate(state.source_box()))

    state.set_zoom(2.0)
    after_box = state.source_box()
    before_center = ((before[0] + before[2]) / 2, (before[1] + before[3]) / 2)
    after_center = (
        ((after_box[0] + after_box[2]) / 2) / state.source_width,
        ((after_box[1] + after_box[3]) / 2) / state.source_height,
    )

    assert after_center == before_center


def test_render_crop_creates_requested_output_size(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "background.jpg"
    Image.new("RGB", (800, 600), "navy").save(source)
    state = CropState(800, 600, 300, 100)

    result = render_crop(str(source), str(destination), state, (1500, 500))

    assert result == str(destination)
    with Image.open(destination) as rendered:
        assert rendered.size == (1500, 500)
