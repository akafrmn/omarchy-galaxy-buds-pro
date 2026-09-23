#!/usr/bin/python3
"""Protocol checks that need no earbuds. Run: /usr/bin/python3 tests/test_protocol.py"""

import importlib.util
import json
import pathlib
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
    assert daemon.state["firmware_update"] == {"build": "R630XXU0AZG2", "label": "Jul 2026"}
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


def ready_to_flash(image_bytes=None, target="R630XXU0AZG2"):
    daemon = gb.Daemon()
    daemon.profile = profile("buds3pro")
    daemon.emit = lambda: None
    daemon.spawn = lambda job: job()
    daemon.socket = FakeSocket()
    image_bytes = image_bytes or make_image()[0]
    daemon.fetch_image = lambda build: image_bytes
    daemon.state.update({
        "connected": True,
        "firmware": {"left": "R630XXU0AZD2", "right": "R630XXU0AZD2", "mismatch": False,
                     "build": gb.decode_firmware("R630XXU0AZD2")},
        "firmware_update": {"build": target, "label": "Jul 2026"},
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
    daemon.fetch_image = lambda build: (_ for _ in ()).throw(OSError("offline"))
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
