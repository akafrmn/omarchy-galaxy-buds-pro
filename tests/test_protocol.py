#!/usr/bin/python3
"""Protocol checks that need no earbuds. Run: /usr/bin/python3 tests/test_protocol.py"""

import importlib.util
import json
import pathlib
import re
import sys
from importlib.machinery import SourceFileLoader

# The daemon has no .py extension, so it needs an explicit source loader.
_path = pathlib.Path(__file__).resolve().parent.parent / "bin" / "galaxy-buds"
_spec = importlib.util.spec_from_loader("galaxy_buds", SourceFileLoader("galaxy_buds", str(_path)))
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)


def profile(name):
    for entry in gb.PROFILES:
        if entry["name"] == name:
            return entry
    raise AssertionError("no profile named " + name)


def test_crc_matches_reference_frame():
    # Frame documented in GalaxyBudsClient's Crc16.cs: msgId 0x61, then payload,
    # then CRC bytes 0x0F 0xF3.
    body = bytes([0x61, 0x02, 0x00, 0x4B, 0x5F, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x00, 0x02, 0x00, 0x13])
    assert gb.crc16(body).to_bytes(2, "little") == bytes([0x0F, 0xF3])


def test_encode_shape():
    frame = gb.encode(gb.MSG_NOISE_CONTROLS, bytes([1]))
    assert frame[0] == gb.SOM and frame[-1] == gb.EOM
    assert frame[1:3] == (4).to_bytes(2, "little")  # msgId + 1 payload + 2 crc
    assert frame[3] == gb.MSG_NOISE_CONTROLS
    assert len(frame) == 8


def test_decode_round_trip():
    stream = gb.encode(gb.MSG_NOISE_CONTROLS, bytes([2])) + gb.encode(gb.MSG_STATUS, bytes(range(8)))
    messages, rest = gb.decode(stream)
    assert rest == b""
    assert messages == [(gb.MSG_NOISE_CONTROLS, bytes([2])), (gb.MSG_STATUS, bytes(range(8)))]


def test_decode_keeps_partial_frame_for_next_read():
    stream = gb.encode(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([1]))
    messages, rest = gb.decode(stream[:5])
    assert messages == [] and rest == stream[:5]
    messages, rest = gb.decode(rest + stream[5:])
    assert messages == [(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([1]))] and rest == b""


def test_decode_resynchronises_after_a_bad_frame():
    # A 0xFD that was really payload: the candidate frame completes but its CRC
    # and end byte are wrong, so the parser steps forward and finds the real one.
    garbage = bytes([0xFD, 0x04, 0x00, 0x63, 0x00, 0x00, 0x00, 0x00])
    frame = gb.encode(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([2]))
    messages, rest = gb.decode(garbage + frame)
    assert messages == [(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([2]))]
    assert rest == b""


def extended_payload():
    payload = bytearray(40)
    payload[0] = 5      # revision
    payload[2] = 97     # battery left
    payload[3] = 95     # battery right
    payload[6] = 0x11   # both worn
    payload[7] = 80     # battery case
    payload[10] = 0x8F  # touchpad unlocked, all four gestures on
    payload[12] = 2     # ambient
    payload[19] = 0     # seamless connection on
    payload[35] = 1     # 360 audio on
    return bytes(payload)


def test_parse_extended_status_buds2pro():
    state = gb.parse_extended_status(extended_payload(), profile("buds2pro"))
    assert state["noise"] == "ambient"
    assert state["battery"] == {"left": 97, "right": 95, "case": 80}
    assert state["wearing"] == {"left": 1, "right": 1}
    assert state["touch"]["enabled"] is True and state["touch"]["tap"] is True
    assert state["seamless"] is True
    assert state["spatial"] is True


def test_unknown_model_hides_spatial_but_keeps_the_rest():
    state = gb.parse_extended_status(extended_payload(), gb.UNKNOWN_PROFILE)
    assert "spatial" not in state
    assert state["noise"] == "ambient"


def test_parse_status():
    payload = bytes([5, 90, 88, 1, 0, 0x11, 70, 0x10])
    state = gb.parse_status(payload, profile("buds2pro"))
    assert state["battery"] == {"left": 90, "right": 88, "case": 70}
    assert state["charging"] == {"left": True, "right": False, "case": False}


def test_touchpad_locked_when_high_bit_clear():
    assert gb.parse_touch(0x0F, "bits7")["enabled"] is False
    assert gb.parse_touch(0x8F, "bits7")["enabled"] is True
    # Older models send one flag, and it means the opposite.
    assert gb.parse_touch(1, "byte")["enabled"] is False
    assert gb.parse_touch(0, "byte")["enabled"] is True


def test_device_id_resolves_to_profile():
    uuids = [gb.SPP_NEW, "d908aab5-7a90-4cbe-8641-86a553db0146"]
    assert gb.device_id_from_uuids(uuids) == 326
    assert gb.profile_for(uuids, "renamed by its owner")["name"] == "buds2pro"


def test_older_models_are_matched_by_name():
    # Buds+ and friends publish no device id, only plain SPP.
    assert gb.profile_for([gb.SPP_STANDARD], "Galaxy Buds+ (1A2B)")["name"] == "budsplus"
    assert gb.profile_for([gb.SPP_STANDARD], "Buds Live (7C3D)")["name"] == "budslive"
    assert gb.profile_for([gb.SPP_LEGACY], "Galaxy Buds (9F11)")["name"] == "buds"
    # "Buds2 Pro" must not be swallowed by the "Buds2" row.
    assert gb.profile_for([gb.SPP_NEW], "Buds2 Pro (0A0A)")["name"] == "buds2pro"
    assert gb.profile_for([gb.SPP_NEW], "Buds3 Pro (0A0A)")["name"] == "buds3pro"


def test_connected_pair_wins_when_two_are_paired():
    idle = ("/org/bluez/hci0/dev_A", {"Connected": False, "Alias": "Galaxy Buds+ (194D)"})
    live = ("/org/bluez/hci0/dev_B", {"Connected": True, "Alias": "Buds2 Pro"})
    assert gb.pick_device([idle, live])[0] == "/org/bluez/hci0/dev_B"
    assert gb.pick_device([live, idle])[0] == "/org/bluez/hci0/dev_B"
    # None connected: still name one, so the panel can say what it waits for.
    assert gb.pick_device([idle])[0] == "/org/bluez/hci0/dev_A"
    assert gb.pick_device([]) == (None, None)


def test_audio_output_decides_between_two_connected_pairs():
    plus = ("/dev_A", {"Connected": True, "Address": "AA:BB:CC:DD:EE:FF"})
    pro = ("/dev_B", {"Connected": True, "Address": "40:35:E6:0C:B4:A1"})
    # Both in your ears: the one you are listening through is the one you mean.
    assert gb.pick_device([plus, pro], "40:35:E6:0C:B4:A1")[0] == "/dev_B"
    # Sound going to the speakers: fall back to whichever is connected.
    assert gb.pick_device([plus, pro], "")[0] == "/dev_A"


def test_link_moves_to_whichever_pair_the_sound_goes_to():
    daemon = gb.Daemon()
    daemon.bus = None
    daemon.socket = object()          # already holding a link
    daemon.state["address"] = "AA:BB:CC:DD:EE:FF"
    daemon.find_device = lambda bus: ("/dev_B", {"Address": "40:35:E6:0C:B4:A1", "Connected": True})

    # Output switched to the other pair, and that pair is connected: hand over.
    daemon.default_address = "40:35:E6:0C:B4:A1"
    assert daemon.should_retarget() is True

    # Output is the pair we already hold: stay.
    daemon.default_address = "AA:BB:CC:DD:EE:FF"
    assert daemon.should_retarget() is False

    # Sound is coming out of the speakers: keep controlling what we have.
    daemon.default_address = ""
    assert daemon.should_retarget() is False

    # Output names a pair that is not there: do not drop a working link for it.
    daemon.default_address = "99:99:99:99:99:99"
    daemon.find_device = lambda bus: (None, None)
    assert daemon.should_retarget() is False


def test_address_from_sink_name():
    assert gb.address_from_sink("bluez_output.40_35_E6_0C_B4_A1.1") == "40:35:E6:0C:B4:A1"
    assert gb.address_from_sink("alsa_output.pci-0000_04_00.6.HiFi__Speaker__sink") == ""
    assert gb.address_from_sink(None) == ""


CARDS = json.dumps([
    {"name": "alsa_card.pci", "profiles": {}},
    {"name": "bluez_card.40_35_E6_0C_B4_A1",
     "active_profile": "a2dp-sink",
     "profiles": {
         "a2dp-sink": {"available": "yes"},
         "a2dp-sink-sbc": {"available": "yes"},
         "a2dp-sink-sbc_xq": {"available": "yes"},
         "a2dp-sink-ldac": {"available": "no"},
         "headset-head-unit": {"available": "yes",
                               "description": "Headset Head Unit (HSP/HFP, codec MSBC)"},
         "headset-head-unit-cvsd": {"available": "yes"},
     }},
])


def in_call(cards_json):
    """Same card, switched to the microphone profile the way PipeWire does
    when an app opens one."""
    cards = json.loads(cards_json)
    for card in cards:
        if card["name"].startswith("bluez_card"):
            card["active_profile"] = "headset-head-unit"
    return json.dumps(cards)

SINKS = json.dumps([
    {"name": "bluez_output.40_35_E6_0C_B4_A1.1",
     "properties": {"api.bluez5.address": "40:35:E6:0C:B4:A1", "api.bluez5.codec": "aac"}},
])


def test_read_codecs_offers_auto_and_the_pinned_profiles():
    codecs = gb.read_codecs(CARDS, SINKS, "40:35:E6:0C:B4:A1")
    # Auto first: it is the profile that picks the best codec both ends support.
    assert [o["label"] for o in codecs["options"]] == ["Auto", "SBC", "SBC-XQ"]
    assert codecs["mode"] == "a2dp"
    assert codecs["options"][0]["value"] == "a2dp-sink"
    # An unavailable profile is not an option.
    assert "LDAC" not in [o["label"] for o in codecs["options"]]
    # No blank buttons.
    assert all(o["label"] for o in codecs["options"])
    # A different pair's card is not this pair's codec list.
    assert gb.read_codecs(CARDS, SINKS, "AA:BB:CC:DD:EE:FF") is None


def test_codec_in_use_comes_from_the_sink():
    # The automatic profile is running AAC, which no profile name would reveal.
    codecs = gb.read_codecs(CARDS, SINKS, "40:35:E6:0C:B4:A1")
    assert codecs["active"] == "a2dp-sink"
    assert codecs["codec"] == "AAC"
    assert gb.active_codec(SINKS, "40:35:E6:0C:B4:A1") == "aac"
    assert gb.active_codec(SINKS, "AA:BB:CC:DD:EE:FF") == ""


def test_codec_labels_are_written_the_way_people_say_them():
    assert gb.codec_label("a2dp-sink-sbc_xq") == "SBC-XQ"
    assert gb.codec_label("a2dp-sink-aptx_hd") == "aptX HD"
    assert gb.codec_label("a2dp-sink-ldac") == "LDAC"
    # Something the table has never heard of still reads sanely.
    assert gb.codec_label("a2dp-sink-brand_new") == "BRAND-NEW"


def test_call_codecs_replace_the_music_ones_while_the_mic_is_open():
    codecs = gb.read_codecs(in_call(CARDS), SINKS, "40:35:E6:0C:B4:A1")
    # The music codecs are not choices at all in this mode.
    assert [o["label"] for o in codecs["options"]] == ["mSBC", "CVSD"]
    assert codecs["mode"] == "headset"
    assert codecs["active"] == "headset-head-unit"


def test_headset_codec_is_read_from_the_description():
    # Plain "headset-head-unit" is mSBC, and only its description says so.
    assert gb.codec_label("headset-head-unit",
                          "Headset Head Unit (HSP/HFP, codec MSBC)") == "mSBC"
    # Translated descriptions keep the codec word.
    assert gb.codec_label("headset-head-unit",
                          "Unidade de headset (HSP/HFP, codec MSBC)") == "mSBC"
    assert gb.codec_label("headset-head-unit-cvsd") == "CVSD"
    # No codec anywhere and not the generic A2DP profile: nothing to label.
    assert gb.codec_label("headset-head-unit", "") == ""


def test_charging_is_only_read_where_the_model_reports_it():
    payload = bytes([5, 90, 88, 1, 0, 0x11, 70, 0x10])
    assert gb.parse_status(payload, profile("buds2pro"))["charging"]["left"] is True
    # Buds+ puts something else in that byte.
    assert "charging" not in gb.parse_status(payload, profile("budsplus"))


def test_plain_spp_devices_are_not_mistaken_for_earbuds():
    assert gb.looks_like_earbuds([gb.SPP_STANDARD], "Keychron K6 Pro") is False
    assert gb.looks_like_earbuds([gb.SPP_STANDARD], "Galaxy Buds+ (1A2B)") is True
    assert gb.looks_like_earbuds([gb.SPP_NEW], "renamed") is True


def budsplus_payload():
    """Buds+ layout: ambient is a flag at 8, touch lock a byte at 12, and
    quick connect only exists from revision 11."""
    payload = bytearray(24)
    payload[0] = 12     # revision
    payload[2] = 70     # battery left
    payload[3] = 68     # battery right
    payload[6] = 0x11   # both worn
    payload[7] = 55     # battery case
    payload[8] = 1      # ambient sound on
    payload[12] = 0     # touchpad unlocked
    payload[21] = 0     # quick connect on
    return bytes(payload)


def test_parse_extended_status_budsplus():
    state = gb.parse_extended_status(budsplus_payload(), profile("budsplus"))
    assert state["noise"] == "ambient"
    assert state["battery"] == {"left": 70, "right": 68, "case": 55}
    assert state["touch"]["enabled"] is True
    assert state["seamless"] is True
    # No 360 Audio on this model: hidden, not guessed.
    assert "spatial" not in state


def test_budsplus_hides_quick_connect_on_old_firmware():
    payload = bytearray(budsplus_payload())
    payload[0] = 9  # revision below the one that reports it
    state = gb.parse_extended_status(bytes(payload), profile("budsplus"))
    assert "seamless" not in state


def test_original_buds_have_no_case_battery():
    payload = bytearray(20)
    payload[2], payload[3] = 60, 58
    payload[6] = 3   # legacy wear state: both
    payload[7] = 1   # ambient on
    state = gb.parse_extended_status(bytes(payload), profile("buds"))
    assert state["battery"] == {"left": 60, "right": 58}
    assert state["wearing"] == {"left": 1, "right": 1}
    assert state["noise"] == "ambient"


def test_noise_command_per_model():
    # Three modes on the newer models...
    assert gb.noise_command("controls", "ambient") == (gb.MSG_NOISE_CONTROLS, bytes([2]))
    # ...ambient sound is a plain toggle on Buds and Buds+...
    assert gb.noise_command("ambient", "ambient") == (gb.MSG_SET_AMBIENT_MODE, bytes([1]))
    assert gb.noise_command("ambient", "off") == (gb.MSG_SET_AMBIENT_MODE, bytes([0]))
    # ...and Buds Live only has ANC on/off.
    assert gb.noise_command("anc", "anc") == (gb.MSG_SET_NOISE_REDUCTION, bytes([1]))


def test_legacy_framing_round_trip():
    frame = gb.encode(gb.MSG_SET_AMBIENT_MODE, bytes([1]), legacy=True)
    assert frame[0] == gb.LEGACY_SOM and frame[-1] == gb.LEGACY_EOM
    assert frame[1] == 0 and frame[2] == 4  # type byte, then size byte
    messages, rest = gb.decode(frame, legacy=True)
    assert messages == [(gb.MSG_SET_AMBIENT_MODE, bytes([1]))] and rest == b""


def test_lock_payload_restores_gestures():
    touch = {"tap": True, "double": False, "triple": True, "hold": False,
             "double_call": True, "hold_call": False}
    assert gb.lock_payload("bits7", True, touch) == bytes([1, 1, 0, 1, 0, 1, 0])
    assert gb.lock_payload("bits7", False, touch) == bytes([0, 1, 0, 1, 0, 1, 0])
    # Turning gestures back on when none are set must not leave a dead touchpad.
    assert gb.lock_payload("bits7", True, {}) == bytes([1, 1, 1, 1, 1, 0, 0])
    assert gb.lock_payload("byte", False, touch) == bytes([1])


def test_cycle_wraps_through_the_models_modes_two_mode_model():
    daemon = gb.Daemon()
    daemon.profile = profile("budsplus")
    daemon.state.update({"modes": ["off", "ambient"], "noise": "ambient"})
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"cycle"}')
    assert sent == [(gb.MSG_SET_AMBIENT_MODE, bytes([0]))]


def test_unsupported_toggles_are_ignored():
    daemon = gb.Daemon()
    daemon.profile = profile("budsplus")
    daemon.emit = lambda: None
    sent = []
    daemon.send = lambda *a, **k: sent.append(a)
    daemon.command('{"cmd":"spatial","value":true}')
    assert sent == []


def test_cycle_wraps_through_the_models_modes():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.state.update({"modes": ["off", "anc", "ambient"], "noise": "ambient"})
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"cycle"}')
    assert sent == [(gb.MSG_NOISE_CONTROLS, bytes([0]))]


def test_ack_applies_the_value_the_earbuds_report():
    daemon = gb.Daemon()
    daemon.state["touch"] = {"enabled": False, "tap": True}
    daemon.emit = lambda: None
    daemon.handle_ack(gb.MSG_NOISE_CONTROLS, bytes([2]))
    assert daemon.state["noise"] == "ambient"
    daemon.handle_ack(gb.MSG_SET_SPATIAL_AUDIO, bytes([1]))
    assert daemon.state["spatial"] is True
    # Seamless is inverted coming back too.
    daemon.handle_ack(gb.MSG_SET_SEAMLESS_CONNECTION, bytes([0]))
    assert daemon.state["seamless"] is True
    daemon.handle_ack(gb.MSG_LOCK_TOUCHPAD, bytes([1]))
    assert daemon.state["touch"] == {"enabled": True, "tap": True}


def test_commands_do_not_guess_state_before_the_ack():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.emit = lambda: None
    daemon.send = lambda *a, **k: None
    daemon.command('{"cmd":"spatial","value":true}')
    assert "spatial" not in daemon.state


def test_stdin_handles_two_commands_arriving_together():
    import os
    read_fd, write_fd = os.pipe()
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.state["modes"] = ["off", "anc", "ambient"]
    daemon.emit = lambda: None
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append(payload)
    os.write(write_fd, b'{"cmd":"noise","value":"off"}\n{"cmd":"noise","value":"anc"}\n')
    daemon.on_stdin(read_fd, 0)
    os.close(write_fd)
    os.close(read_fd)
    assert sent == [bytes([0]), bytes([1])]


def test_seamless_is_inverted_on_the_wire():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"seamless","value":true}')
    assert sent == [(gb.MSG_SET_SEAMLESS_CONNECTION, bytes([0]))]



def test_bud_in_the_case_is_named_not_read_as_empty():
    # Left in the case (3), right in the ear (1); the case bud reports 0.
    payload = bytes([5, 0, 64, 1, 0, 0x31, 70, 0x00])
    state = gb.parse_status(payload, profile("buds3pro"))
    assert state["battery"]["left"] == 0
    assert state["placement"] == {"left": "case", "right": "wearing"}


def test_bud_dropped_off_the_link_is_disconnected():
    payload = bytes([5, 0, 71, 1, 0, 0x02, 0, 0x00])
    state = gb.parse_status(payload, profile("buds2pro"))
    assert state["placement"] == {"left": "disconnected", "right": "idle"}


def test_extended_status_carries_placement():
    payload = bytearray(40)
    payload[0] = 3
    payload[2], payload[3] = 0, 55
    payload[6] = 0x31
    state = gb.parse_extended_status(bytes(payload), profile("buds3pro"))
    assert state["placement"] == {"left": "case", "right": "wearing"}


def test_unknown_placement_nibble_is_not_guessed():
    assert gb.parse_placement(0x9F, "nibbles") == {"left": "unknown", "right": "unknown"}


def test_original_buds_placement_is_worn_or_idle():
    assert gb.parse_placement(1, "legacy") == {"left": "wearing", "right": "idle"}


# ---- the Galaxy Buds Pro line -------------------------------------------

PRO_LINE = {
    # name suffix is the last four hex digits of the address
    "budspro": ("Galaxy Buds Pro (6F2A)", [gb.SPP_STANDARD], None),
    "buds2pro": ("Galaxy Buds2 Pro (6F2A)", [gb.SPP_NEW], 325),
    "buds3pro": ("Galaxy Buds3 Pro (D5AB)", [gb.SPP_NEW], 341),
    "buds4pro": ("Galaxy Buds4 Pro (6F2A)", [gb.SPP_NEW], 361),
}


def device_uuid(device_id):
    return gb.DEVICE_ID_UUID_PREFIX + format(device_id, "04x")


def test_every_pro_model_is_matched_by_its_advertised_name():
    for expected, (name, uuids, _) in PRO_LINE.items():
        assert gb.profile_for(uuids, name)["name"] == expected, name


def test_every_pro_model_with_a_device_id_survives_renaming():
    for expected, (_, uuids, device_id) in PRO_LINE.items():
        if device_id is None:
            continue  # the 2021 Buds Pro publishes no id and cannot be renamed
        assert gb.profile_for(uuids + [device_uuid(device_id)], "Kitchen buds")["name"] == expected


def test_buds4_pro_is_not_swallowed_by_the_buds4_row():
    assert gb.profile_for([gb.SPP_NEW], "Galaxy Buds4 (1B2C)")["name"] == "buds4"
    assert gb.profile_for([gb.SPP_NEW], "Hector's Buds4 Pro")["name"] == "buds4pro"
    for device_id in (359, 360, 361):
        assert gb.profile_for([gb.SPP_NEW, device_uuid(device_id)], "")["name"] == "buds4pro"


def test_the_original_buds_pro_is_not_mistaken_for_a_newer_pro():
    assert gb.profile_for([gb.SPP_STANDARD], "Galaxy Buds Pro (0A0A)")["uuid"] == gb.SPP_STANDARD


def test_parse_extended_status_every_pro_since_buds2():
    for name in ("buds2pro", "buds3pro", "buds4pro"):
        state = gb.parse_extended_status(extended_payload(), profile(name))
        assert state["noise"] == "ambient", name
        assert state["battery"] == {"left": 97, "right": 95, "case": 80}, name
        assert state["touch"]["enabled"] is True, name
        assert state["seamless"] is True, name
        assert state["spatial"] is True, name


def test_buds4_pro_noise_ack_is_a_receipt_not_a_mode():
    daemon = gb.Daemon()
    daemon.profile = profile("buds4pro")
    daemon.emit = lambda: None
    daemon.state["noise"] = "ambient"
    daemon.handle_ack(gb.MSG_NOISE_CONTROLS, bytes([0]))
    assert daemon.state["noise"] == "ambient"
    # The applied mode arrives on its own.
    daemon.handle(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([1]))
    assert daemon.state["noise"] == "anc"


def test_a_charging_bud_is_in_the_case_whatever_its_nibble_says():
    # Captured from a Buds4 Pro: right reports idle (2) with its charging bit set.
    state = gb.parse_status(bytes([1, 50, 60, 1, 0, 0x12, 70, 0x04]), profile("buds4pro"))
    assert state["placement"] == {"left": "wearing", "right": "case"}
    assert state["charging"]["right"] is True


def test_commands_that_are_not_json_objects_are_ignored():
    daemon = gb.Daemon()
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append(msg_id)
    for line in ("", "x", "{", "[]", "null", '"cycle"', "42", '{"cmd": 1}'):
        daemon.command(line)
    assert sent == []


def test_one_bud_noise_setting_is_read_on_buds3_pro_and_later():
    # Captured live from a Buds3 Pro: left worn, right idle, setting off.
    payload = bytearray(61)
    payload[0], payload[6], payload[12], payload[28] = 4, 0x12, 0, 0
    state = gb.parse_extended_status(bytes(payload), profile("buds3pro"))
    assert state["one_bud_noise"] is False
    assert state["placement"] == {"left": "wearing", "right": "idle"}
    payload[28] = 1
    for name in ("buds3pro", "buds4pro"):
        assert gb.parse_extended_status(bytes(payload), profile(name))["one_bud_noise"] is True


def test_one_bud_noise_is_omitted_where_the_offset_is_unknown():
    for name in ("budspro", "buds2pro"):
        assert "one_bud_noise" not in gb.parse_extended_status(extended_payload(), profile(name))


def test_refused_anc_ack_shows_the_mode_the_buds_kept():
    # Live Buds3 Pro with one bud worn: ANC requested, firmware acks Off.
    daemon = gb.Daemon()
    daemon.profile = profile("buds3pro")
    daemon.emit = lambda: None
    daemon.handle_ack(gb.MSG_NOISE_CONTROLS, bytes([0]))
    assert daemon.state["noise"] == "off"


def test_closed_case_counts_as_in_the_case():
    # Live Buds3 Pro, both docked and the lid shut: nibble 4, full and not charging.
    state = gb.parse_status(bytes([4, 100, 100, 1, 0, 0x44, 35, 0x00]), profile("buds3pro"))
    assert state["placement"] == {"left": "case", "right": "case"}


# ---- firmware -------------------------------------------------------------

# msg 104 exactly as a Buds3 Pro sent it on connect.
LIVE_VERSION_INFO = bytes.fromhex(
    "02025236333058585530415a443200000000000000005236333058585530415a4432"
    "00000000000000000000")

# Trimmed from the live build list for Buds3Pro (newest first, as served).
LIVE_BUILDS = [{"buildName": b, "modelString": "R630"} for b in
               ("R630XXU0AZG2", "R630XXU0AZD2", "R630XXU0AZD1", "R630XXU0AYJ1", "R630XXU0AXG5")]


def firmware_daemon(fetch):
    daemon = gb.Daemon()
    daemon.profile = profile("buds3pro")
    daemon.emit = lambda: None
    daemon.fetch_firmware = fetch
    daemon.spawn = lambda job: job()
    return daemon


def test_version_info_is_read_per_bud():
    assert gb.parse_version_info(LIVE_VERSION_INFO) == {"left": "R630XXU0AZD2", "right": "R630XXU0AZD2"}
    assert gb.parse_version_info(bytes(2) + b"R640XXU0AZD2" + bytes(8)) == {"left": "R640XXU0AZD2"}
    assert gb.parse_version_info(bytes([2, 2, 0xFF, 0x00, 0x41])) == {}


def test_firmware_build_is_decoded():
    fw = gb.decode_firmware("R630XXU0AZD2")
    assert (fw["model"], fw["year"], fw["month"], fw["revision"], fw["label"]) == ("R630", 2026, 4, 2, "Apr 2026")
    assert gb.decode_firmware("R630XXU0AZG2")["label"] == "Jul 2026"
    assert gb.decode_firmware("R630XXU0AXG5")["year"] == 2024
    for bad in ("", "R630", "R630XXU0AZM2", "X630XXU0AZD2", None, 42):
        assert gb.decode_firmware(bad) is None, bad


def test_firmware_ordering_uses_year_month_then_base36_revision():
    order = ["R630XXU0AYJ1", "R630XXU0AZC3", "R630XXU0AZD1", "R630XXU0AZD9", "R630XXU0AZDA", "R630XXU0AZG2"]
    keys = [gb.firmware_key(gb.decode_firmware(b)) for b in order]
    assert keys == sorted(keys)


def test_latest_build_finds_the_newer_release_for_the_same_model():
    assert gb.latest_build(LIVE_BUILDS, "R630XXU0AZD2")["build"] == "R630XXU0AZG2"
    assert gb.latest_build(LIVE_BUILDS, "R630XXU0AZG2") is None
    other = [{"buildName": "R640XXU0AZZ9"}]
    assert gb.latest_build(other, "R630XXU0AZD2") is None
    for junk in (None, {}, "x", [None, 3, {"buildName": 7}]):
        assert gb.latest_build(junk, "R630XXU0AZD2") is None


def test_version_message_updates_state_and_checks_for_an_update():
    calls = []
    daemon = firmware_daemon(lambda model: calls.append(model) or LIVE_BUILDS)
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware"]["build"]["label"] == "Apr 2026"
    assert daemon.state["firmware"]["mismatch"] is False
    assert daemon.state["firmware_update"] == {"build": "R630XXU0AZG2", "label": "Jul 2026",
                                               "installable": True}
    assert calls == ["Buds3Pro"]
    # A second report of the same build does not ask again within 12 hours.
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert calls == ["Buds3Pro"]


def test_firmware_check_off_never_touches_the_network():
    def fetch(model):
        raise AssertionError("fetched while disabled")
    daemon = firmware_daemon(fetch)
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert "firmware_update" not in daemon.state
    assert daemon.state["firmware"]["left"] == "R630XXU0AZD2"


def test_turning_the_check_off_clears_the_notice():
    daemon = firmware_daemon(lambda model: LIVE_BUILDS)
    daemon.command('{"cmd":"firmware_check","value":true}')
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert "firmware_update" in daemon.state
    daemon.command('{"cmd":"firmware_check","value":false}')
    assert "firmware_update" not in daemon.state
    # Back on within 12 hours: the remembered answer returns without a request.
    daemon.fetch_firmware = lambda model: (_ for _ in ()).throw(AssertionError("fetched again"))
    daemon.command('{"cmd":"firmware_check","value":true}')
    assert daemon.state["firmware_update"]["build"] == "R630XXU0AZG2"


def test_a_failing_lookup_is_silent():
    for failure in (OSError("offline"), ValueError("bad json"), TimeoutError()):
        def fetch(model, failure=failure):
            raise failure
        daemon = firmware_daemon(fetch)
        daemon.firmware_check = True
        daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
        assert "firmware_update" not in daemon.state
        assert "firmware" in daemon.state


def test_different_builds_per_bud_are_flagged():
    payload = bytes(2) + b"R630XXU0AZD2" + bytes(8) + b"R630XXU0AZC3" + bytes(8)
    daemon = firmware_daemon(lambda model: [])
    daemon.handle(gb.MSG_VERSION_INFO_LONG, payload)
    assert daemon.state["firmware"]["mismatch"] is True
    assert daemon.state["firmware"]["build"]["build"] == "R630XXU0AZD2"


def test_every_model_names_its_firmware_list():
    for entry in gb.PROFILES:
        assert entry.get("fw_model"), entry["name"]
    assert gb.profile_get(gb.UNKNOWN_PROFILE, "fw_model") is None


# ---- firmware installation --------------------------------------------------

import struct  # noqa: E402
import zlib  # noqa: E402


def make_image(build="R630XXU0AZG2", model=b"SM-R630", segments=((6, 1234), (7, 777))):
    """A synthetic image in Samsung's container layout. Segment bytes are
    pseudo-random but carry the model and build strings like a real one."""
    datas = []
    for index, (_, size) in enumerate(segments):
        body = bytes((i * 31 + index * 7) & 0xFF for i in range(size))
        if index == 0:
            tag = model + b"\0" + build.encode()
            body = tag + body[len(tag):]
        datas.append(body)
    header_size = 12 + 16 * len(segments)
    table, blob, offset = b"", b"", header_size
    for (seg_id, _), body in zip(segments, datas, strict=True):
        table += struct.pack("<iIii", seg_id, zlib.crc32(body), offset, len(body))
        blob += body
        offset += len(body)
    total = header_size + len(blob) + 4
    image = struct.pack("<IiI", 0xCAFECAFE, total, len(segments)) + table + blob
    return image + struct.pack("<I", zlib.crc32(datas[-1])), datas


class FakeSocket:
    def __init__(self):
        self.frames = []
        self.closed = False

    def sendall(self, data):
        self.frames.append(bytes(data))

    def close(self):
        self.closed = True

    def fileno(self):
        return -1


def sent(sock, msg_id=None):
    """(msg_id, payload, flags) for every frame written, optionally filtered."""
    out = []
    for frame in sock.frames:
        flags = struct.unpack_from("<H", frame, 1)[0] & 0xF000
        (mid, payload), = gb.decode(frame)[0]
        if msg_id is None or mid == msg_id:
            out.append((mid, payload, flags))
    return out


def pin(data):
    import hashlib
    return (len(data), hashlib.sha256(data).hexdigest())


def ready_to_flash(image_bytes=None, target="R630XXU0AZG2"):
    daemon = gb.Daemon()
    daemon.profile = profile("buds3pro")
    daemon.emit = lambda: None
    daemon.spawn = lambda job: job()
    daemon.socket = FakeSocket()
    image_bytes = image_bytes or make_image()[0]
    def fetch_image(build, progress=lambda done, total: None):
        # Report the download in three steps like a real chunked read.
        for part in (1, 2, 3):
            progress(len(image_bytes) * part // 3, len(image_bytes))
        return image_bytes
    daemon.fetch_image = fetch_image
    daemon.pinned = {target: pin(image_bytes)}
    daemon.state.update({
        "connected": True,
        "firmware": {"left": "R630XXU0AZD2", "right": "R630XXU0AZD2", "mismatch": False,
                     "build": gb.decode_firmware("R630XXU0AZD2")},
        "firmware_update": {"build": target, "label": "Jul 2026", "installable": True},
        "placement": {"left": "wearing", "right": "idle"}, "wearing": {"left": 1, "right": 2},
        "battery": {"left": 80, "right": 75, "case": 50}})
    return daemon


def pull_segment(daemon, seg_id, size, per_request=5):
    """Play the earbud: announce the segment, request it all by offset."""
    daemon.handle(gb.MSG_FOTA_CONTROL, struct.pack("<Bh", 1, seg_id))
    before = len(daemon.socket.frames)
    offset, mtu = 0, daemon.flash["mtu"]
    while offset < size:
        daemon.handle(gb.MSG_FOTA_DOWNLOAD_DATA, struct.pack("<I", offset) + bytes([per_request]))
        offset += mtu * per_request
    chunks = [f for f in daemon.socket.frames[before:]]
    got, lasts = b"", []
    for frame in chunks:
        flags = struct.unpack_from("<H", frame, 1)[0] & 0xF000
        (mid, payload), = gb.decode(frame)[0]
        assert mid == gb.MSG_FOTA_DOWNLOAD_DATA and flags == gb.FLAG_RESPONSE | gb.FLAG_FRAGMENT
        header = struct.unpack_from("<I", payload)[0]
        assert header & 0x7FFFFFFF == len(got), "chunks must arrive at the offsets asked for"
        lasts.append(not header & 0x80000000)
        got += payload[4:]
    return got, lasts


def test_simulated_earbud_pulls_the_whole_image_and_installs_it():
    image, datas = make_image()
    daemon = ready_to_flash(image)
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    (mid, payload, flags), = sent(daemon.socket)
    assert mid == gb.MSG_FOTA_OPEN and flags == 0
    crc, count = struct.unpack_from("<IB", payload)
    assert count == 2 and crc == zlib.crc32(datas[-1])
    assert struct.unpack_from("<BII", payload, 5) == (6, len(datas[0]), zlib.crc32(datas[0]))

    daemon.handle(gb.MSG_FOTA_OPEN, bytes([0]))
    daemon.handle(gb.MSG_FOTA_CONTROL, struct.pack("<Bh", 0, 900))   # asks for more than allowed
    assert sent(daemon.socket, gb.MSG_FOTA_CONTROL)[-1] == (gb.MSG_FOTA_CONTROL, struct.pack("<Bh", 0, 650),
                                                              gb.FLAG_RESPONSE)
    daemon.flash["mtu"] = 100   # small chunks exercise many requests
    for seg_id, body in ((6, datas[0]), (7, datas[1])):
        got, lasts = pull_segment(daemon, seg_id, len(body))
        assert got == body
        assert lasts[-1] is True and not any(lasts[:-1])
    assert daemon.state["firmware_install"]["stage"] == "transferring"

    daemon.handle(gb.MSG_FOTA_UPDATE, bytes([1, 0, 0]))
    assert sent(daemon.socket, gb.MSG_FOTA_UPDATE)[-1] == (gb.MSG_FOTA_UPDATE, bytes([1]), gb.FLAG_RESPONSE)
    daemon.handle(gb.MSG_FOTA_RESULT, bytes([0, 0]))
    assert sent(daemon.socket, gb.MSG_FOTA_RESULT)[-1] == (gb.MSG_FOTA_RESULT, bytes([1]), gb.FLAG_RESPONSE)
    assert daemon.state["firmware_install"]["stage"] == "rebooting"

    daemon.disconnect()   # they restart to install
    assert daemon.state["firmware_install"]["stage"] == "rebooting"
    new = bytes(2) + b"R630XXU0AZG2" + bytes(8) + b"R630XXU0AZG2" + bytes(8)
    daemon.handle(gb.MSG_VERSION_INFO_LONG, new)
    assert daemon.state["firmware_install"] == {"stage": "done", "target": "R630XXU0AZG2"}
    assert "firmware_update" not in daemon.state and daemon.flash is None


def test_restart_on_the_old_build_is_reported_as_not_applied():
    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    daemon.handle(gb.MSG_FOTA_OPEN, bytes([0]))
    daemon.handle(gb.MSG_FOTA_RESULT, bytes([0, 0]))
    daemon.disconnect()
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)   # still AZD2
    assert daemon.state["firmware_install"]["stage"] == "failed"
    assert "did not apply" in daemon.state["firmware_install"]["error"]


def test_preflight_refuses_everything_unsafe():
    cases = {
        "downgrade": lambda st: st.update(firmware_update={"build": "R630XXU0AYJ1"}),
        "same build": lambda st: st.update(firmware_update={"build": "R630XXU0AZD2"}),
        "other model": lambda st: st.update(firmware_update={"build": "R640XXU0AZG2"}),
        "mismatch": lambda st: st["firmware"].update(mismatch=True),
        "one bud gone": lambda st: st["firmware"].pop("right"),
        "low battery": lambda st: st["battery"].update(left=29),
        "closed case": lambda st: st["wearing"].update(right=4),
        "dropped bud": lambda st: st["placement"].update(right="disconnected"),
        "not connected": lambda st: st.update(connected=False),
        "unknown installed build": lambda st: st["firmware"].pop("build"),
    }
    for name, breakage in cases.items():
        daemon = ready_to_flash()
        breakage(daemon.state)
        assert gb.flash_preflight(daemon.state, daemon.profile, daemon.state["firmware_update"]["build"]), name
    daemon = ready_to_flash()
    assert gb.flash_preflight(daemon.state, daemon.profile, "R630XXU0AZG2") == []
    assert gb.flash_preflight(daemon.state, daemon.profile, "R630XXU0AZH1"), "only the offered build"


def test_refused_install_sends_nothing():
    daemon = ready_to_flash()
    daemon.state["battery"]["right"] = 10
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    assert daemon.socket.frames == []
    assert daemon.state["firmware_install"]["stage"] == "refused"
    assert any("30%" in reason for reason in daemon.state["firmware_install"]["reasons"])


def test_image_verification_rejects_bad_files():
    good, _ = make_image()
    gb.verify_firmware_image(good, "R630XXU0AZG2")
    # Real Buds3 Pro images mention the sibling SM-R530 in a shared template.
    gb.verify_firmware_image(make_image(model=b"SM-R630 VERSNAME:1,SM-R530")[0], "R630XXU0AZG2")
    corrupt = bytearray(good)
    corrupt[200] ^= 0xFF
    truncated = good[:-10]
    bad = {
        "magic": b"\0\0\0\0" + good[4:],
        "truncated": truncated,
        "crc": bytes(corrupt),
        "other model": make_image(model=b"SM-R510")[0],
        "foreign build inside": make_image(model=b"SM-R630 R510XXU0AZG2")[0],
        "other build": make_image(build="R630XXU0AZF1")[0],
        "tiny": b"\xfe\xca",
    }
    for name, data in bad.items():
        try:
            gb.verify_firmware_image(data, "R630XXU0AZG2")
        except gb.FirmwareError:
            continue
        raise AssertionError(f"{name} image was accepted")


def test_download_or_verification_failure_sends_nothing():
    daemon = ready_to_flash(make_image(model=b"SM-R510")[0])
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    assert daemon.socket.frames == []
    assert daemon.state["firmware_install"]["stage"] == "failed"
    assert daemon.state["firmware_install"]["error"].startswith("Nothing was sent")

    daemon = ready_to_flash()
    daemon.fetch_image = lambda build, progress: (_ for _ in ()).throw(OSError("offline"))
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    assert daemon.socket.frames == [] and daemon.flash is None


def test_session_error_connection_loss_cancel_and_watchdog_all_fail_safe():
    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    daemon.handle(gb.MSG_FOTA_OPEN, bytes([144]))
    assert "session error 144" in daemon.state["firmware_install"]["error"] and daemon.flash is None

    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    daemon.handle(gb.MSG_FOTA_OPEN, bytes([0]))
    daemon.disconnect()
    assert daemon.state["firmware_install"]["stage"] == "failed" and daemon.flash is None

    daemon = ready_to_flash()
    sock = daemon.socket
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    daemon.command('{"cmd":"firmware_cancel"}')
    assert daemon.state["firmware_install"]["error"].startswith("Cancelled") and sock.closed

    daemon = ready_to_flash()
    now = [1000.0]
    daemon.clock = lambda: now[0]
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    daemon.handle(gb.MSG_FOTA_OPEN, bytes([0]))
    now[0] += 19
    daemon.flash_watchdog()
    assert daemon.flash is not None
    now[0] += 5
    daemon.flash_watchdog()
    assert daemon.flash is None and "stopped answering" in daemon.state["firmware_install"]["error"]


def test_nothing_else_talks_to_the_earbuds_during_an_install():
    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    frames = len(daemon.socket.frames)
    for line in ('{"cmd":"noise","value":"anc"}', '{"cmd":"cycle"}', '{"cmd":"spatial","value":true}'):
        daemon.command(line)
    assert len(daemon.socket.frames) == frames
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')   # second request ignored
    assert len(daemon.socket.frames) == frames


def test_fota_chunk_header_and_flags_survive_our_own_decoder():
    data = bytes(range(250))
    assert struct.unpack_from("<I", gb.fota_chunk(data, 0, 100))[0] == 0x80000000
    assert struct.unpack_from("<I", gb.fota_chunk(data, 200, 100))[0] == 200
    assert len(gb.fota_chunk(data, 200, 100)) == 4 + 50
    assert gb.fota_chunk(data, 250, 100) is None
    frame = gb.encode(gb.MSG_FOTA_DOWNLOAD_DATA, gb.fota_chunk(data, 0, 100), flags=gb.FLAG_RESPONSE | gb.FLAG_FRAGMENT)
    assert struct.unpack_from("<H", frame, 1)[0] & 0xF000 == 0x3000
    assert gb.decode(frame)[0][0][0] == gb.MSG_FOTA_DOWNLOAD_DATA


def test_firmware_status_says_latest_available_unknown_or_off():
    daemon = firmware_daemon(lambda model: LIVE_BUILDS[1:])   # AZD2 is the newest listed
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_latest"]["status"] == "latest"
    assert isinstance(daemon.state["firmware_latest"]["checked"], int)

    daemon = firmware_daemon(lambda model: LIVE_BUILDS)
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_latest"]["status"] == "available"

    calls = []
    def offline(model):
        calls.append(model)
        raise OSError("offline")
    daemon = firmware_daemon(offline)
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_latest"]["status"] == "unknown"
    daemon.check_firmware()   # a failure is retried at the next chance, not in 12 hours
    assert len(calls) == 2

    daemon = firmware_daemon(lambda model: {"not": "a list"})
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_latest"]["status"] == "unknown"

    daemon.command('{"cmd":"firmware_check","value":false}')
    assert daemon.state["firmware_latest"]["status"] == "off"


def test_firmware_status_is_checking_while_the_lookup_runs():
    pending = []
    daemon = firmware_daemon(lambda model: LIVE_BUILDS)
    daemon.spawn = pending.append          # hold the worker
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_latest"] == {"status": "checking"}
    pending[0]()
    assert daemon.state["firmware_latest"]["status"] == "available"


def test_install_reports_download_and_transfer_progress():
    image, datas = make_image(segments=((6, 3000),))
    daemon = ready_to_flash(image)
    seen = []
    daemon.emit = lambda: seen.append(dict(daemon.state.get("firmware_install") or {}))
    now = [0.0]
    daemon.clock = lambda: now[0]
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    downloads = [s for s in seen if s.get("stage") == "downloading" and s.get("total")]
    assert [s["percent"] for s in downloads] == [33, 66, 100]
    assert downloads[-1]["bytes"] == len(image)

    daemon.handle(gb.MSG_FOTA_OPEN, bytes([0]))
    daemon.handle(gb.MSG_FOTA_CONTROL, struct.pack("<Bh", 0, 100))
    daemon.handle(gb.MSG_FOTA_CONTROL, struct.pack("<Bh", 1, 6))
    daemon.handle(gb.MSG_FOTA_DOWNLOAD_DATA, struct.pack("<I", 0) + bytes([5]))
    first = daemon.state["firmware_install"]
    assert (first["bytes"], first["total"], first["eta"]) == (500, 3000, None)   # too early to guess
    now[0] = 10.0
    daemon.handle(gb.MSG_FOTA_DOWNLOAD_DATA, struct.pack("<I", 500) + bytes([10]))
    later = daemon.state["firmware_install"]
    assert later["bytes"] == 1500 and later["percent"] == 50
    assert later["eta"] == 10   # 1500 bytes took 10 s, 1500 left


def test_a_late_install_result_is_acknowledged():
    # Seen live after an install: the earbuds repeat "185 00 00" on every
    # connect until the host answers it.
    daemon = ready_to_flash()
    daemon.handle(gb.MSG_FOTA_RESULT, bytes([0, 0]))
    assert sent(daemon.socket) == [(gb.MSG_FOTA_RESULT, bytes([1]), gb.FLAG_RESPONSE)]
    assert "firmware_install" not in daemon.state
    # Other firmware messages outside an install are still ignored.
    daemon.handle(gb.MSG_FOTA_CONTROL, bytes([0, 100, 0]))
    assert len(daemon.socket.frames) == 1

# ---- pinned images ----------------------------------------------------------

def test_pinned_rows_are_well_formed_pro_builds():
    pro = {"R190", "R510", "R630", "R640"}
    assert gb.PINNED_FIRMWARE, "at least one reviewed build"
    for build, (size, digest) in gb.PINNED_FIRMWARE.items():
        decoded = gb.decode_firmware(build)
        assert decoded and decoded["model"] in pro, build
        assert isinstance(size, int) and 0 < size <= 32 * 1024 * 1024, build
        assert re.fullmatch(r"[0-9a-f]{64}", digest), build


def test_unpinned_build_is_offered_without_install():
    builds = [{"buildName": "R630XXU0AZL9"}]   # newer than anything pinned
    daemon = firmware_daemon(lambda model: builds)
    daemon.firmware_check = True
    daemon.handle(gb.MSG_VERSION_INFO_LONG, LIVE_VERSION_INFO)
    assert daemon.state["firmware_update"]["installable"] is False
    daemon = ready_to_flash(target="R630XXU0AZL9")
    daemon.pinned = {}
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZL9"}')
    assert daemon.socket.frames == []
    assert daemon.state["firmware_install"]["stage"] == "refused"
    assert any("not reviewed" in r for r in daemon.state["firmware_install"]["reasons"])


def test_image_that_differs_from_its_pin_is_never_sent():
    image, _ = make_image()
    swapped = make_image(segments=((6, 1234), (7, 778)))[0]   # valid container, other bytes
    for served in (swapped, image[:-1], image + b"\0"):
        daemon = ready_to_flash(image)
        daemon.fetch_image = lambda build, progress=None, served=served: served
        daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
        assert daemon.socket.frames == []
        assert daemon.state["firmware_install"]["stage"] == "failed"
        assert "does not match the reviewed" in daemon.state["firmware_install"]["error"]


class FakeResponse:
    def __init__(self, data, url):
        self.data, self.url = data, url

    def read(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fetch_with(served, url=None, pinned=None, clock=None):
    """fetch_firmware_image against a fake opener: (bytes or FirmwareError, what it asked for)."""
    import urllib.request
    image, _ = make_image()
    pinned = pinned if pinned is not None else {"R630XXU0AZG2": pin(image)}
    seen = {}

    class Opener:
        def open(self, request, timeout):
            seen.update(url=request.full_url, timeout=timeout)
            return FakeResponse(served, url or request.full_url)

    def build_opener(*handlers):
        seen["handlers"] = handlers
        return Opener()

    real = urllib.request.build_opener
    urllib.request.build_opener = build_opener
    try:
        kwargs = {"clock": clock} if clock else {}
        return gb.fetch_firmware_image("R630XXU0AZG2", pinned=pinned, **kwargs), seen
    except gb.FirmwareError as error:
        return error, seen
    finally:
        urllib.request.build_opener = real


def test_fetch_returns_only_the_pinned_bytes_and_never_redirects():
    image, _ = make_image()
    result, seen = fetch_with(image)
    assert result == image
    assert seen["url"] == "https://fw.timschneeberger.me/v3/firmware/download/R630XXU0AZG2"
    assert seen["timeout"] == gb.FIRMWARE_CONNECT_TIMEOUT
    handler, = seen["handlers"]
    try:
        handler().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/")
        raise AssertionError("redirect followed")
    except gb.FirmwareError:
        pass


def test_fetch_refuses_oversize_unpinned_slow_and_foreign_downloads():
    image, _ = make_image()
    ticks = iter(range(0, 10 ** 6, gb.FIRMWARE_DOWNLOAD_DEADLINE + 1))
    cases = {
        "oversize": fetch_with(image + bytes(1024 * 1024)),
        "unpinned": fetch_with(image, pinned={}),
        "other host": fetch_with(image, url="https://elsewhere.example/R630XXU0AZG2"),
        "wrong bytes": fetch_with(make_image(segments=((6, 1234), (7, 778)))[0]),
        "too slow": fetch_with(image, clock=lambda: next(ticks)),
    }
    for name, (result, _) in cases.items():
        assert isinstance(result, gb.FirmwareError), name
    assert cases["unpinned"][1] == {}, "an unpinned build is never requested"


# ---- BlueZ restarts --------------------------------------------------------

class FakeDBusException(Exception):
    pass


def fake_dbus():
    """register_profile imports dbus; CI has no python-dbus, and only the
    exception type is needed."""
    import types
    module = types.ModuleType("dbus")
    module.DBusException = FakeDBusException
    sys.modules.setdefault("dbus", module)
    return sys.modules["dbus"]


class FakeManager:
    def __init__(self, fail=False):
        self.fail = fail
        self.registered = []

    def UnregisterProfile(self, path):
        raise fake_dbus().DBusException("org.bluez.Error.DoesNotExist")

    def RegisterProfile(self, path, uuid, options):
        if self.fail:
            raise fake_dbus().DBusException("org.freedesktop.DBus.Error.ServiceUnknown")
        self.registered.append(uuid)


def restartable_daemon():
    fake_dbus()
    daemon = gb.Daemon()
    daemon.profile = profile("buds3pro")
    daemon.emit = lambda: None
    daemon.profile_path = "/omarchy/galaxybuds"
    daemon.manager = FakeManager()
    daemon.managers = []
    daemon.bluez_up = True
    def profile_manager():
        if not daemon.bluez_up:
            # dbus-python's get_object raises when nobody owns org.bluez.
            raise FakeDBusException("org.freedesktop.DBus.Error.NameHasNoOwner")
        daemon.managers.append(FakeManager())
        return daemon.managers[-1]
    daemon.profile_manager = profile_manager
    return daemon


def test_bluez_restart_drops_the_link_and_registers_again():
    daemon = restartable_daemon()
    daemon.socket = sock = FakeSocket()
    daemon.registered = True
    daemon.state.update({"connected": True, "battery": {"left": 80, "right": 75}})
    daemon.on_bluez_owner_changed("org.bluez", ":1.5", ":1.409")
    assert sock.closed and daemon.socket is None, "the dead bluetoothd's link is closed"
    assert daemon.state["connected"] is False
    assert daemon.registered, "the new bluetoothd gets our profile right away"
    assert daemon.manager is daemon.managers[-1], "the proxy follows the new bluetoothd"
    assert daemon.manager.registered == [gb.SPP_NEW]


def test_bluez_gone_waits_for_it_to_come_back():
    daemon = restartable_daemon()
    daemon.registered = True
    daemon.on_bluez_owner_changed("org.bluez", ":1.5", "")
    assert not daemon.registered and not daemon.managers, "nothing to register with yet"
    assert daemon.register_profile() is True, "the retry timer stays alive"


def test_register_timer_survives_a_successful_registration():
    daemon = restartable_daemon()
    daemon.registered = True
    assert daemon.register_profile() is True, "returning False would cancel the GLib timer"


def test_unknown_profile_on_connect_registers_again():
    daemon = restartable_daemon()
    daemon.registered = True
    daemon.manager = FakeManager(fail=True)
    daemon.on_connect_error(Exception("org.bluez.Error.InvalidArguments: br-connection-profile-unavailable"))
    assert not daemon.registered and daemon.state["reason"] == "connect failed"
    daemon.register_profile()
    assert not daemon.registered and daemon.state["reason"] == "profile busy"
    assert daemon.manager is daemon.managers[-1], "a failed registration rebuilds the proxy"
    daemon.register_profile()
    assert daemon.registered and daemon.manager.registered == [gb.SPP_NEW]


def stale_link_daemon():
    daemon = restartable_daemon()
    daemon.registered = True
    daemon.scheduled = []
    daemon.schedule = lambda ms, job: daemon.scheduled.append((ms, job))
    return daemon


def test_connect_without_a_socket_registers_again():
    # After a bluetoothd crash mid-connect, BlueZ kept counting a link we no
    # longer held: every ConnectProfile succeeded and no NewConnection came.
    daemon = stale_link_daemon()
    daemon.connecting = True
    daemon.on_connect_reply()
    assert [ms for ms, _ in daemon.scheduled] == [gb.STALE_LINK_MS], "a late socket gets a moment"
    assert daemon.registered
    _, check = daemon.scheduled.pop()
    assert check() is False, "a one-shot timer"
    assert not daemon.registered and daemon.state["reason"] == "connect failed"
    daemon.register_profile()
    assert daemon.registered and daemon.manager.registered == [gb.SPP_NEW]


def test_already_connected_without_a_socket_registers_again():
    daemon = stale_link_daemon()
    daemon.on_connect_error(Exception("org.bluez.Error.AlreadyConnected: Already Connected"))
    _, check = daemon.scheduled.pop()
    check()
    assert not daemon.registered


def test_socket_that_arrives_keeps_the_registration():
    daemon = stale_link_daemon()
    daemon.on_connect_reply()
    daemon.link_up(FakeSocket())        # NewConnection came in during the grace
    _, check = daemon.scheduled.pop()
    check()
    assert daemon.registered and daemon.state["connected"] is True
    daemon.on_connect_reply()
    daemon.on_connect_error(Exception("org.bluez.Error.AlreadyConnected"))
    assert not daemon.scheduled, "a live link needs no check"


def test_socket_that_came_and_went_keeps_the_registration():
    daemon = stale_link_daemon()
    daemon.on_connect_reply()
    daemon.link_up(FakeSocket())
    daemon.disconnect()                 # dropped again within the grace
    _, check = daemon.scheduled.pop()
    check()
    assert daemon.registered, "the profile delivered a socket, so it is not stale"


def test_stale_link_check_spares_a_newer_registration():
    # bluetoothd restarted during the grace: the check was about the old
    # profile and must leave the new registration alone.
    daemon = stale_link_daemon()
    daemon.on_connect_reply()
    daemon.on_bluez_owner_changed("org.bluez", ":1.5", ":1.409")
    assert daemon.registered
    _, check = daemon.scheduled.pop()
    check()
    assert daemon.registered and daemon.manager.registered == [gb.SPP_NEW]


def test_registration_keeps_retrying_while_bluez_is_away():
    daemon = restartable_daemon()
    daemon.manager = FakeManager(fail=True)
    daemon.bluez_up = False
    assert daemon.register_profile() is True, "no bluetoothd must not cancel the retry timer"
    assert not daemon.registered and not daemon.managers
    daemon.on_bluez_owner_changed("org.bluez", "", ":1.409")   # raced: gone again
    assert not daemon.registered
    daemon.bluez_up = True
    assert daemon.register_profile() is True   # stale proxy fails, a fresh one is made
    assert daemon.register_profile() is True
    assert daemon.registered and daemon.manager.registered == [gb.SPP_NEW]


def test_other_connect_errors_keep_the_registration():
    daemon = restartable_daemon()
    daemon.registered = True
    daemon.on_connect_error(Exception("org.bluez.Error.Failed: Protocol not available"))
    assert daemon.registered
    daemon.on_connect_error(Exception("org.bluez.Error.AlreadyConnected"))
    assert daemon.registered


# ---- plugin update check --------------------------------------------------

def update_daemon(version="2.5.0", release=None, error=None):
    daemon = gb.Daemon()
    daemon.emit = lambda: None
    daemon.spawn = lambda job: job()
    daemon.version = version
    daemon.now = 1000.0
    daemon.clock = lambda: daemon.now
    daemon.fetches = 0
    def fetch_release():
        daemon.fetches += 1
        if error:
            raise error
        return release if release is not None else {"tag_name": "v2.5.0"}
    daemon.fetch_release = fetch_release
    return daemon


def test_parse_version():
    assert gb.parse_version("v2.4.1") == (2, 4, 1)
    assert gb.parse_version("2.10.0") > gb.parse_version("2.9.9")
    for bad in ("dev", "", None, "v2.5", "2.5.0-rc1"):
        assert gb.parse_version(bad) is None, bad


def test_plugin_version_is_reported_before_any_check():
    daemon = gb.Daemon()
    assert daemon.state["plugin"] == {"version": gb.plugin_version()}
    assert gb.parse_version(gb.plugin_version()), "the manifest version is what the panel shows"


def test_update_check_off_makes_no_request():
    daemon = update_daemon()
    daemon.check_plugin_update()
    daemon.command(json.dumps({"cmd": "update_check", "value": False}))
    assert daemon.fetches == 0
    assert daemon.state["plugin"] == {"version": "2.5.0", "status": "off"}


def test_update_check_says_latest():
    daemon = update_daemon(release={"tag_name": "v2.5.0"})
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    plugin = daemon.state["plugin"]
    assert plugin["status"] == "latest" and plugin["version"] == "2.5.0" and plugin["latest"] == "2.5.0"
    assert isinstance(plugin["checked"], int)


def test_update_check_offers_a_newer_release():
    daemon = update_daemon(release={"tag_name": "v2.10.0", "html_url": "https://evil.example/"})
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    plugin = daemon.state["plugin"]
    assert plugin["status"] == "available" and plugin["latest"] == "2.10.0"
    assert plugin["url"] == "https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.10.0", \
        "the link is built from the version, never taken from the response"


def test_update_check_ignores_older_drafts_and_prereleases():
    daemon = update_daemon(release={"tag_name": "v2.4.1"})
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    assert daemon.state["plugin"]["status"] == "latest", "running something newer than the release"
    for release in ({"tag_name": "v9.0.0", "prerelease": True}, {"tag_name": "v9.0.0", "draft": True},
                    {"tag_name": "nightly"}, [], "nope"):
        daemon = update_daemon(release=release)
        daemon.command(json.dumps({"cmd": "update_check", "value": True}))
        assert daemon.state["plugin"]["status"] == "unknown", release


def test_update_check_failure_retries_and_success_is_cached():
    daemon = update_daemon(error=OSError("offline"))
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    assert daemon.state["plugin"]["status"] == "unknown" and daemon.fetches == 1
    daemon.check_plugin_update()
    assert daemon.fetches == 2, "a failed check is retried on the next tick"

    daemon = update_daemon(release={"tag_name": "v2.6.0"})
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    checked = daemon.state["plugin"]["checked"]
    daemon.command(json.dumps({"cmd": "update_check", "value": False}))
    daemon.now += 3600
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    assert daemon.fetches == 1, "at most one request every 12 hours"
    assert daemon.state["plugin"]["status"] == "available" and daemon.state["plugin"]["checked"] == checked
    daemon.now += gb.FIRMWARE_RECHECK
    daemon.check_plugin_update()
    assert daemon.fetches == 2


def test_dev_checkout_has_nothing_to_compare():
    daemon = update_daemon(version="dev", release={"tag_name": "v2.5.0"})
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    assert daemon.state["plugin"] == {"version": "dev", "status": "unknown"}


def test_update_check_works_during_a_firmware_transfer():
    daemon = update_daemon(release={"tag_name": "v2.5.0"})
    daemon.flash = {"stage": "transferring"}
    daemon.command(json.dumps({"cmd": "update_check", "value": True}))
    assert daemon.state["plugin"]["status"] == "latest"


# ---- equalizer --------------------------------------------------------------

# Extended status captured from a Buds3 Pro on R630XXU0AZG2 (revision 4) with
# a custom curve set in Galaxy Wearable: byte 9 is 6. Noise off, left bud out
# of the ear, right in the open case.
BUDS3PRO_CUSTOM_EQ = bytes.fromhex(
    "04 08 5c 64 01 00 23 53 00 06 ff 22 00 00 55 01 55 01 03 00 04 5a 00 04 04 10 00 01 00 00 00"
    " 02 00 01 00 01 00 00 00 00 00 00 00 00 00 00 01 01 00 02 00 03 00 01 ff 01 02 00 00 00 00")


def eq_daemon(name="buds3pro"):
    daemon = gb.Daemon()
    daemon.profile = profile(name) if name else gb.UNKNOWN_PROFILE
    daemon.emit = lambda: None
    daemon.socket = FakeSocket()
    return daemon


def test_eq_captured_buds3_pro_status_reads_custom():
    state = gb.parse_extended_status(BUDS3PRO_CUSTOM_EQ, profile("buds3pro"))
    assert state["revision"] == 4
    assert state["eq"] == "custom"
    assert state["noise"] == "off"
    assert state["battery"] == {"left": 92, "right": 100, "case": 83}


def test_eq_payload_byte_per_preset():
    expected = {"off": 0, "bass": 1, "soft": 2, "dynamic": 3, "clear": 4, "treble": 5}
    for preset, byte in expected.items():
        daemon = eq_daemon()
        daemon.command(json.dumps({"cmd": "eq", "value": preset}))
        frame = daemon.socket.frames[0]
        assert frame[3] == 0x86 and frame[4:5] == bytes([byte]), preset
        assert sent(daemon.socket) == [(gb.MSG_EQUALIZER, bytes([byte]), 0)], preset


def test_eq_command_never_sends_custom_or_unknown_values():
    for value in ("custom", "unknown", "loud", "", 3, 6, 7, None, ["bass"], {"preset": "bass"}):
        daemon = eq_daemon()
        daemon.command(json.dumps({"cmd": "eq", "value": value}))
        assert daemon.socket.frames == [], value


def test_eq_byte_sits_at_11_on_buds_plus_and_9_from_buds_live_on():
    payload = bytearray(budsplus_payload())
    payload[9], payload[11] = 3, 1
    assert gb.parse_extended_status(bytes(payload), profile("budsplus"))["eq"] == "bass"
    payload = bytearray(extended_payload())
    payload[9], payload[11] = 3, 1
    for name in ("budslive", "budspro", "buds2pro", "buds3pro", "buds4pro"):
        assert gb.parse_extended_status(bytes(payload), profile(name))["eq"] == "dynamic", name


def test_eq_is_hidden_only_where_the_model_does_not_report_it():
    payload = bytearray(20)
    payload[6], payload[11] = 3, 2   # the original Buds keep their own EQ byte at 11
    assert "eq" not in gb.parse_extended_status(bytes(payload), profile("buds"))
    assert "eq" not in gb.parse_extended_status(BUDS3PRO_CUSTOM_EQ, gb.UNKNOWN_PROFILE)
    for name in ("buds", None):
        daemon = eq_daemon(name)
        daemon.command('{"cmd":"eq","value":"bass"}')
        assert daemon.socket.frames == [], name
        daemon.handle_ack(gb.MSG_EQUALIZER, bytes([1]))
        assert "eq" not in daemon.state, name


def test_eq_unknown_byte_keeps_the_control():
    for byte in (7, 8, 0x42, 0xFF):
        payload = bytearray(BUDS3PRO_CUSTOM_EQ)
        payload[9] = byte
        assert gb.parse_extended_status(bytes(payload), profile("buds3pro"))["eq"] == "unknown", byte
        daemon = eq_daemon()
        daemon.handle_ack(gb.MSG_EQUALIZER, bytes([byte]))
        assert daemon.state["eq"] == "unknown", byte
    # The presets can still be picked from there.
    daemon.command('{"cmd":"eq","value":"clear"}')
    assert sent(daemon.socket) == [(gb.MSG_EQUALIZER, bytes([4]), 0)]


def test_eq_custom_curve_is_replaced_by_a_preset():
    daemon = eq_daemon()
    daemon.handle(gb.MSG_EXTENDED_STATUS, BUDS3PRO_CUSTOM_EQ)
    assert daemon.state["eq"] == "custom"
    daemon.command('{"cmd":"eq","value":"soft"}')
    daemon.handle(gb.MSG_ACK, bytes([gb.MSG_EQUALIZER, 2]))
    assert daemon.state["eq"] == "soft"


def test_eq_is_blocked_during_a_firmware_transfer():
    daemon = eq_daemon()
    daemon.flash = {"stage": "transferring"}
    daemon.command('{"cmd":"eq","value":"bass"}')
    assert daemon.socket.frames == []
    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    frames = len(daemon.socket.frames)
    daemon.command('{"cmd":"eq","value":"treble"}')
    assert len(daemon.socket.frames) == frames


def test_eq_follows_the_ack_not_the_click():
    daemon = eq_daemon()
    daemon.state["eq"] = "off"
    daemon.command('{"cmd":"eq","value":"bass"}')
    assert daemon.state["eq"] == "off", "no guessing before the earbuds answer"
    daemon.handle(gb.MSG_ACK, bytes([gb.MSG_EQUALIZER, 1]))
    assert daemon.state["eq"] == "bass"
    # The earbuds' answer wins over what was asked for.
    daemon.command('{"cmd":"eq","value":"treble"}')
    daemon.handle(gb.MSG_ACK, bytes([gb.MSG_EQUALIZER, 4]))
    assert daemon.state["eq"] == "clear"
    # An empty ack changes nothing.
    daemon.handle(gb.MSG_ACK, bytes([gb.MSG_EQUALIZER]))
    assert daemon.state["eq"] == "clear"


def test_eq_ack_is_the_applied_preset_on_buds4_too():
    # Unlike their noise control ack, Buds4 models answer EQ with the value.
    daemon = eq_daemon("buds4pro")
    daemon.command('{"cmd":"eq","value":"soft"}')
    daemon.handle_ack(gb.MSG_EQUALIZER, bytes([0]))
    assert daemon.state["eq"] == "off"
    # A dropped link forgets a request that was never answered.
    daemon.command('{"cmd":"eq","value":"bass"}')
    assert daemon.eq_requested == "bass"
    daemon.disconnect()
    assert daemon.eq_requested is None
# ---- find my earbuds ----

def finding_daemon(left="idle", right="idle", model="buds3pro"):
    daemon = gb.Daemon()
    daemon.profile = profile(model)
    daemon.emit = lambda: None
    daemon.socket = FakeSocket()
    daemon.now = 1000.0
    daemon.clock = lambda: daemon.now
    daemon.scheduled = []
    daemon.schedule = lambda ms, job: daemon.scheduled.append((ms, job))
    daemon.state.update({"connected": True, "find": gb.find_idle(),
                         "placement": {"left": left, "right": right}})
    return daemon


def find_frames(daemon):
    return [(mid, payload) for mid, payload, _ in sent(daemon.socket)]


def tick(daemon):
    """Fire every live watchdog timer once, as GLib would; True while one runs."""
    jobs, daemon.scheduled = daemon.scheduled, []
    for ms, job in jobs:
        if job():
            daemon.scheduled.append((ms, job))
    return daemon.find_ticking != 0


def status_with(left, right):
    """MSG_STATUS payload with placement nibbles (1 worn, 2 idle, 3 case, 0 off the link)."""
    return bytes([5, 80, 75, 1, 0, (left << 4) | right, 70, 0x00])


def test_find_start_stop_and_mute_frames():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    assert find_frames(daemon) == [(160, b"")], "no mute when no bud is worn"
    find = daemon.state["find"]
    assert find["active"] is True and find["muted"] == {"left": False, "right": False}
    assert abs(find["until"] - (gb.time.time() + 90)) < 5
    assert [ms for ms, _ in daemon.scheduled] == [gb.FIND_TICK_MS], "the watchdog runs while it rings"
    daemon.command('{"cmd":"find_mute","value":{"left":true,"right":false}}')
    assert find_frames(daemon)[-1] == (162, bytes([1, 0]))
    assert daemon.state["find"]["muted"]["left"] is False, "nothing assumed before the earbuds report"
    daemon.command('{"cmd":"find_stop"}')
    assert find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"] == gb.find_idle() and daemon.find is None
    assert gb.MSG_FIND_START == 160 and gb.MSG_FIND_STOP == 161 and gb.MSG_MUTE_EARBUD == 162
    assert not any(mid == 166 for mid, _ in find_frames(daemon)), "never ring while worn"


def test_find_mutes_a_worn_bud_right_after_start():
    daemon = finding_daemon(left="wearing", right="case")
    daemon.command('{"cmd":"find_start"}')
    assert find_frames(daemon) == [(160, b""), (162, bytes([1, 0]))]
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([1, 0]))
    assert daemon.find["confirm_by"] is None
    assert daemon.state["find"]["muted"] == {"left": True, "right": False}
    # The user can't unmute the bud in the ear from the panel either.
    daemon.command('{"cmd":"find_mute","value":{"left":false,"right":false}}')
    assert find_frames(daemon)[-1] == (162, bytes([1, 0]))


def test_find_stops_when_the_mute_is_not_confirmed_in_two_seconds():
    daemon = finding_daemon(right="wearing")
    daemon.command('{"cmd":"find_start"}')
    assert [ms for ms, _ in daemon.scheduled] == [gb.FIND_TICK_CONFIRM_MS], "fast ticks while unconfirmed"
    daemon.now += 1.9
    assert tick(daemon) is True and daemon.find is not None
    daemon.now += 0.2
    tick(daemon)
    assert daemon.find is None and daemon.find_ticking == 0
    assert find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"]["active"] is False and daemon.state["find"]["reason"] == "no_confirm"


def test_find_ignores_a_stale_unsafe_report_while_confirming():
    daemon = finding_daemon(right="wearing")
    daemon.command('{"cmd":"find_start"}')
    frames = len(daemon.socket.frames)
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([0, 0]))   # before our mute landed
    assert daemon.state["find"]["muted"] == {"left": False, "right": False}
    assert daemon.find["confirm_by"] is not None and len(daemon.socket.frames) == frames
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([1, 0]))   # not the worn bud: still unsafe
    assert daemon.state["find"]["muted"] == {"left": False, "right": False}, "an unsafe report is not shown"
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([0, 1]))
    assert daemon.find["confirm_by"] is None and daemon.state["find"]["muted"] == {"left": False, "right": True}


def test_find_mute_ack_counts_as_confirmation():
    daemon = finding_daemon(left="wearing")
    daemon.command('{"cmd":"find_start"}')
    daemon.handle(gb.MSG_ACK, bytes([gb.MSG_MUTE_EARBUD, 1, 0]))
    assert daemon.find["confirm_by"] is None
    daemon.now += 5
    assert daemon.find_watchdog() is True


def test_find_refuses_when_both_buds_are_worn():
    daemon = finding_daemon(left="wearing", right="wearing")
    daemon.command('{"cmd":"find_start"}')
    assert daemon.socket.frames == [] and daemon.find is None
    assert daemon.state["find"] == dict(gb.find_idle(), reason="both_worn")
    # No placement report yet counts as possibly worn.
    daemon = finding_daemon()
    daemon.state.pop("placement")
    daemon.command('{"cmd":"find_start"}')
    assert daemon.socket.frames == [] and daemon.state["find"]["reason"] == "unknown_placement"
    # One worn, the other off the link: nothing could ring.
    daemon = finding_daemon(left="wearing", right="disconnected")
    daemon.command('{"cmd":"find_start"}')
    assert daemon.socket.frames == [] and daemon.state["find"]["reason"] == "none_can_ring"


def test_find_refused_after_a_reconnect_until_the_buds_report_placement():
    daemon = finding_daemon()
    daemon.disconnect()
    assert "placement" not in daemon.state and "wearing" not in daemon.state
    # Whatever a previous session said must not survive a new link either.
    daemon.state["placement"] = {"left": "idle", "right": "idle"}
    daemon.link_up(FakeSocket())
    assert daemon.state["connected"] is True and "placement" not in daemon.state
    daemon.command('{"cmd":"find_start"}')
    assert daemon.socket.frames == [] and daemon.state["find"]["reason"] == "unknown_placement"
    daemon.handle(gb.MSG_STATUS, status_with(1, 2))   # fresh report: left worn
    daemon.command('{"cmd":"find_start"}')
    assert find_frames(daemon) == [(160, b""), (162, bytes([1, 0]))]


def test_find_refused_after_a_hand_over_to_another_pair():
    daemon = finding_daemon()
    daemon.default_address = "AA:BB:CC:DD:EE:FF"
    daemon.should_retarget = lambda: True
    daemon.connect = lambda: True
    originals = gb.pactl, gb.address_from_sink
    gb.pactl = lambda *args: ""   # no PipeWire in tests
    gb.address_from_sink = lambda name: "AA:BB:CC:DD:EE:FF"
    try:
        daemon.refresh_audio()
    finally:
        gb.pactl, gb.address_from_sink = originals
    assert "placement" not in daemon.state
    daemon.link_up(FakeSocket())
    daemon.command('{"cmd":"find_start"}')
    assert daemon.socket.frames == [] and daemon.state["find"]["reason"] == "unknown_placement"


def test_find_mutes_a_bud_that_goes_into_an_ear_mid_search():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    assert [ms for ms, _ in daemon.scheduled] == [gb.FIND_TICK_MS]
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([0, 1]))   # the user muted the right one
    daemon.handle(gb.MSG_STATUS, status_with(1, 2))            # left goes in
    assert find_frames(daemon)[-1] == (162, bytes([1, 1])), "the new worn bud is muted, the right stays muted"
    assert daemon.find["confirm_by"] == daemon.now + gb.FIND_MUTE_CONFIRM_LATE == daemon.now + 1
    assert daemon.find_ticking == gb.FIND_TICK_CONFIRM_MS, "fast ticks while the mute is unconfirmed"
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([1, 1]))
    assert daemon.find["confirm_by"] is None
    tick(daemon)
    assert daemon.find_ticking == gb.FIND_TICK_MS, "back to the slow period once confirmed"
    assert [ms for ms, _ in daemon.scheduled] == [gb.FIND_TICK_MS], "one live timer at a time"
    # After that, a report with the worn bud unmuted ends the search.
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([0, 1]))
    assert daemon.find is None and find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"]["reason"] == "unsafe_unmute"
    # Both going in stops it outright.
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    daemon.handle(gb.MSG_STATUS, status_with(1, 1))
    assert daemon.find is None and find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"]["reason"] == "both_worn"


def test_find_mid_search_mute_gets_one_second():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    daemon.handle(gb.MSG_STATUS, status_with(2, 1))   # right goes in, no confirmation follows
    daemon.now += 0.9
    tick(daemon)
    assert daemon.find is not None
    daemon.now += 0.1
    tick(daemon)
    assert daemon.find is None and daemon.state["find"]["reason"] == "no_confirm"
    assert find_frames(daemon)[-1] == (161, b"")


def test_find_stops_when_the_only_bud_that_could_ring_drops_off():
    daemon = finding_daemon(left="wearing", right="idle")
    daemon.command('{"cmd":"find_start"}')
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([1, 0]))
    daemon.handle(gb.MSG_STATUS, status_with(1, 0))   # right drops off the link
    assert daemon.find is None and find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"]["reason"] == "none_can_ring"


def test_find_stops_by_itself_after_90_seconds():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    daemon.now += 89
    assert tick(daemon) is True
    daemon.now += 1
    tick(daemon)
    assert daemon.find is None and daemon.find_ticking == 0
    assert find_frames(daemon)[-1] == (161, b"")
    assert daemon.state["find"]["reason"] == "timeout"
    # The earbuds answering our stop with their own 161 keeps the message.
    daemon.handle(gb.MSG_FIND_STOP, b"")
    assert daemon.state["find"]["reason"] == "timeout"


def test_find_cleared_when_the_buds_stop_on_their_own():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    frames = len(daemon.socket.frames)
    daemon.handle(gb.MSG_FIND_STOP, b"")
    assert daemon.find is None and daemon.state["find"] == dict(gb.find_idle(), reason="buds_stopped")
    assert len(daemon.socket.frames) == frames, "nothing sent back"


def test_find_mute_report_updates_state_without_an_echo():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    frames = len(daemon.socket.frames)
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([1, 1]))
    daemon.handle(gb.MSG_MUTE_EARBUD_UPDATED, bytes([0, 1]))
    assert daemon.state["find"]["muted"] == {"left": False, "right": True}
    assert len(daemon.socket.frames) == frames, "163 is never echoed back"


def test_find_cleared_on_disconnect_without_sending():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    sock = daemon.socket
    frames = len(sock.frames)
    daemon.disconnect()
    assert daemon.find is None and daemon.state["find"] == gb.find_idle()
    assert len(sock.frames) == frames
    tick(daemon)
    assert daemon.find_ticking == 0, "the timer ends with the search"


def test_find_blocked_during_a_firmware_install():
    daemon = ready_to_flash()
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    frames = len(daemon.socket.frames)
    daemon.command('{"cmd":"find_start"}')
    assert len(daemon.socket.frames) == frames and daemon.find is None
    assert daemon.state["find"]["reason"] == "firmware"


def test_find_stops_when_a_firmware_install_starts():
    daemon = ready_to_flash()
    daemon.state["placement"] = {"left": "idle", "right": "idle"}
    daemon.command('{"cmd":"find_start"}')
    assert daemon.find is not None
    daemon.command('{"cmd":"firmware_install","value":"R630XXU0AZG2"}')
    mids = [mid for mid, _, _ in sent(daemon.socket)]
    assert mids[:3] == [160, 161, gb.MSG_FOTA_OPEN], "stop goes out before the transfer"
    assert daemon.find is None and daemon.state["find"]["reason"] == "firmware_started"


def test_find_stops_before_the_helper_exits():
    import os

    class Loop:
        quit_called = False

        def quit(self):
            self.quit_called = True

    daemon = finding_daemon()
    daemon.loop = Loop()
    daemon.command('{"cmd":"find_start"}')
    read_fd, write_fd = os.pipe()
    os.close(write_fd)   # the shell went away: EOF
    assert daemon.on_stdin(read_fd, 0) is False
    os.close(read_fd)
    assert find_frames(daemon)[-1] == (161, b"") and daemon.loop.quit_called
    # Nothing running: exit sends nothing.
    daemon = finding_daemon()
    daemon.loop = Loop()
    assert daemon.shutdown() is False and daemon.socket.frames == [] and daemon.loop.quit_called


def test_find_hands_over_with_a_stop_when_the_audio_moves_to_another_pair():
    daemon = finding_daemon()
    daemon.command('{"cmd":"find_start"}')
    sock = daemon.socket
    daemon.default_address = "AA:BB:CC:DD:EE:FF"
    daemon.should_retarget = lambda: True
    daemon.connect = lambda: True
    originals = gb.pactl, gb.address_from_sink
    gb.pactl = lambda *args: ""   # no PipeWire in tests
    gb.address_from_sink = lambda name: "AA:BB:CC:DD:EE:FF"
    try:
        daemon.refresh_audio()
    finally:
        gb.pactl, gb.address_from_sink = originals
    assert [gb.decode(f)[0][0][0] for f in sock.frames][-1] == 161 and sock.closed


def test_find_is_offered_on_every_model_and_frames_legacy_too():
    for entry in gb.PROFILES:
        assert gb.profile_get(entry, "find") is True, entry["name"]
    daemon = finding_daemon(model="buds")
    daemon.command('{"cmd":"find_start"}')
    (mid, payload), = gb.decode(daemon.socket.frames[0], legacy=True)[0]
    assert (mid, payload) == (160, b"")


def test_find_refused_when_not_connected():
    daemon = finding_daemon()
    daemon.socket = None
    daemon.state["connected"] = False
    daemon.command('{"cmd":"find_start"}')
    assert daemon.find is None and daemon.state["find"]["reason"] == "not_connected"
    # Stop with nothing running only clears the message.
    daemon.command('{"cmd":"find_stop"}')
    assert daemon.state["find"] == gb.find_idle()


def test_find_reasons_are_codes_the_panel_translates():
    source = _path.read_text()
    refusal = source[source.index("def find_refusal"):source.index("def mute_payload")]
    emitted = set(re.findall(r'return "([a-z_]+)"', refusal))
    emitted |= set(re.findall(r'(?:find_stop\(|reason ?= ?)"([a-z_]+)"', source))
    assert emitted == set(gb.FIND_REASONS), emitted ^ set(gb.FIND_REASONS)
    daemon = finding_daemon()
    daemon.profile = dict(profile("buds3pro"), find=False)
    daemon.command('{"cmd":"find_start"}')
    assert daemon.state["find"]["reason"] == "unsupported" and daemon.socket.frames == []
    root = _path.parent.parent
    panel, readme, manifest = ((root / name).read_text() for name in ("Panel.qml", "README.md", "manifest.json"))
    for code in gb.FIND_REASONS:
        match = re.search(r'"%s": t\("(\w+)"' % code, panel)
        assert match, f"Panel.qml does not translate {code}"
        assert match.group(1) in readme and match.group(1) in manifest, match.group(1)


if __name__ == "__main__":
    failures = 0
    for name, test in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            test()
            print(f"ok   {name}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL {name}: {error}")
    sys.exit(1 if failures else 0)
