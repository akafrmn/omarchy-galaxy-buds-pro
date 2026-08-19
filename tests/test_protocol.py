#!/usr/bin/python3
"""Protocol checks that need no earbuds. Run: /usr/bin/python3 tests/test_protocol.py"""

import importlib.util
import pathlib
import sys
from importlib.machinery import SourceFileLoader

# The daemon has no .py extension, so it needs an explicit source loader.
_path = pathlib.Path(__file__).resolve().parent.parent / "bin" / "galaxy-buds"
_spec = importlib.util.spec_from_loader("galaxy_buds", SourceFileLoader("galaxy_buds", str(_path)))
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)


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
    state = gb.parse_extended_status(extended_payload(), gb.PROFILES["buds2pro"])
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
    state = gb.parse_status(payload)
    assert state["battery"] == {"left": 90, "right": 88, "case": 70}
    assert state["charging"] == {"left": True, "right": False, "case": False}


def test_touchpad_locked_when_high_bit_clear():
    assert gb.parse_touch(0x0F)["enabled"] is False
    assert gb.parse_touch(0x8F)["enabled"] is True


def test_device_id_resolves_to_profile():
    uuids = ["0000110b-0000-1000-8000-00805f9b34fb",
             "d908aab5-7a90-4cbe-8641-86a553db0146"]
    device_id = gb.device_id_from_uuids(uuids)
    assert device_id == 326
    assert gb.profile_for_device_id(device_id)[0] == "buds2pro"
    assert gb.profile_for_device_id(341)[0] == "buds3pro"
    assert gb.profile_for_device_id(999)[0] == "unknown"


def test_lock_payload_restores_gestures():
    touch = {"tap": True, "double": False, "triple": True, "hold": False,
             "double_call": True, "hold_call": False}
    assert gb.lock_payload("bits7", True, touch) == bytes([1, 1, 0, 1, 0, 1, 0])
    assert gb.lock_payload("bits7", False, touch) == bytes([0, 1, 0, 1, 0, 1, 0])
    # Turning gestures back on when none are set must not leave a dead touchpad.
    assert gb.lock_payload("bits7", True, {}) == bytes([1, 1, 1, 1, 1, 0, 0])
    assert gb.lock_payload("byte", False, touch) == bytes([1])


def test_cycle_wraps_through_the_models_modes():
    daemon = gb.Daemon()
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
    daemon.emit = lambda: None
    daemon.send = lambda *a, **k: None
    daemon.command('{"cmd":"spatial","value":true}')
    assert "spatial" not in daemon.state


def test_seamless_is_inverted_on_the_wire():
    daemon = gb.Daemon()
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"seamless","value":true}')
    assert sent == [(gb.MSG_SET_SEAMLESS_CONNECTION, bytes([0]))]


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
