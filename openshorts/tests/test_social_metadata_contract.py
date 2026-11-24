from types import SimpleNamespace

import app


def _request(**values):
    defaults = {"description": None, "tiktok_description": None,
                "instagram_description": None, "youtube_title": None,
                "youtube_description": None, "title": None,
                "scheduled_date": None, "timezone": "UTC", "platforms": []}
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_social_metadata_routes_each_clip_field_to_its_platform():
    clip = {
        "video_description_for_tiktok": "TikTok clip A",
        "video_description_for_instagram": "Instagram clip A",
        "video_title_for_youtube_short": "YouTube title A",
        "video_description_for_youtube_short": "YouTube description A",
    }

    metadata = app._social_metadata_for_clip(_request(), clip)

    assert metadata == {
        "tiktok_description": "TikTok clip A",
        "instagram_description": "Instagram clip A",
        "youtube_title": "YouTube title A",
        "youtube_description": "YouTube description A",
    }


def test_specific_request_fields_outrank_clip_and_legacy_description():
    clip = {"video_description_for_tiktok": "Stored TikTok",
            "video_description_for_instagram": "Stored Instagram",
            "video_description_for_youtube_short": "Stored YouTube"}
    metadata = app._social_metadata_for_clip(_request(
        description="Legacy shared", tiktok_description="Edited TikTok",
        youtube_title="Edited title", youtube_description="Edited YouTube"), clip)

    assert metadata["tiktok_description"] == "Edited TikTok"
    assert metadata["instagram_description"] == "Stored Instagram"
    assert metadata["youtube_title"] == "Edited title"
    assert metadata["youtube_description"] == "Edited YouTube"


def test_legacy_description_is_only_a_per_field_fallback():
    metadata = app._social_metadata_for_clip(_request(description="Old client caption"), {
        "video_description_for_tiktok": "Stored TikTok",
        "video_description_for_youtube_short": "Stored YouTube",
    })

    assert metadata["tiktok_description"] == "Stored TikTok"
    assert metadata["instagram_description"] == "Old client caption"
    assert metadata["youtube_description"] == "Stored YouTube"


def test_upload_payload_maps_combined_platforms_to_independent_texts():
    req = _request(platforms=["tiktok", "instagram", "youtube"],
        tiktok_description="TikTok text", instagram_description="Instagram text",
        youtube_title="YouTube title", youtube_description="YouTube description")

    payload = app._build_social_upload_payload(req, {}, "profile")

    assert payload["tiktok_title"] == "TikTok text"
    assert payload["instagram_title"] == "Instagram text"
    assert payload["youtube_title"] == "YouTube title"
    assert payload["youtube_description"] == "YouTube description"


def test_upload_payload_for_single_platform_does_not_emit_other_platform_copy():
    tiktok = app._build_social_upload_payload(
        _request(platforms=["tiktok"], tiktok_description="Only TikTok"), {}, "profile")
    youtube = app._build_social_upload_payload(
        _request(platforms=["youtube"], youtube_title="Only title",
                 youtube_description="Only YouTube"), {}, "profile")

    assert tiktok["tiktok_title"] == "Only TikTok"
    assert "youtube_description" not in tiktok
    assert youtube["youtube_title"] == "Only title"
    assert youtube["youtube_description"] == "Only YouTube"
    assert "tiktok_title" not in youtube


def test_old_description_request_still_publishes_via_legacy_fallback():
    payload = app._build_social_upload_payload(
        _request(platforms=["tiktok", "youtube"], description="Legacy caption"), {}, "profile")

    assert payload["tiktok_title"] == "Legacy caption"
    assert payload["youtube_description"] == "Legacy caption"
