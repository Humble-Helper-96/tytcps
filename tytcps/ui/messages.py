# SPDX-License-Identifier: GPL-3.0-or-later
"""The error catalogue.

A message is chosen on the engine's error `code` AND its `radio` state, and
always says what happened to the radio: nothing was written, the radio holds
what was asked for, or its contents are now unknown and how to fix that.
"""

import re
from dataclasses import dataclass, field

from PyQt6.QtWidgets import QMessageBox

from ..backend.fleet import short_unit

NOTHING = "Nothing was written."
UNCHANGED = "Nothing was written; the radio is unchanged."


@dataclass
class Msg:
    id: str
    title: str
    body: str
    state: str = ""          # what happened to the radio
    severe: bool = False     # the radio is not fit for use
    buttons: list = field(default_factory=list)   # action names
    detail: str = ""         # the engine's own sentence


def explain(res, context=""):
    """Msg for a failed RunResult."""
    e = res.error or {}
    code = e.get("code") or res.code
    radio = e.get("radio", "unknown")
    detail = e.get("message", "")

    # A run that got as far as writing and then said nothing about it (no
    # error event: killed, or an exit code alone) is never explained from
    # its exit code: "no radio" after an erase would claim nothing was written.
    if not res.errors and res.command.radio and res.reached("erase", "write", "verify", "keys"):
        return _unknown_state(res, "The programming engine stopped unexpectedly.", detail)
    if code == "unit_mismatch":
        body = "Identify the radio and try again."
        if e.get("a207") and e.get("expected"):
            body = "This is unit %s, not unit %s. %s" % (short_unit(e["a207"]),
                                                        short_unit(e["expected"]), body)
        return Msg("E-R8", "A different radio is connected.", body, UNCHANGED, detail=detail)
    if code == "no_radio":
        return Msg("E-R1", "No radio found.",
                   "Check the cable is in fully at both ends and the radio is on.",
                   NOTHING, buttons=["retry"], detail=detail)
    if code == "no_permission":
        return Msg("E-U1", "Can't open the radio.",
                   "Your user needs permission to use the programming cable. Settings → USB "
                   "access can set this up.",
                   NOTHING, buttons=["fix_usb"], detail=detail)
    if code == "busy":
        return Msg("E-U3", "The radio is in use by another program.",
                   "Usually a virtual machine with USB passthrough. Shut it down (pausing isn't "
                   "enough) and close any other programming software.",
                   NOTHING, buttons=["retry"], detail=detail)
    if code == "multiple_radios":
        return Msg("E-U4", "Two radios are connected.",
                   "Connect one at a time. They can't be told apart over USB.", NOTHING,
                   detail=detail)
    if code == "unsupported_model":
        model = e.get("model") or _quoted(detail) or "something else"
        return Msg("E-R6", "This radio model isn't supported for keys.",
                   'It\'s a "%s". Keys can only be written to the MD-UV390 and MD-UV380 Plus.'
                   % model, NOTHING, detail=detail)
    if code == "reads_disagree":
        return Msg("E-R3", "Two reads of the radio didn't match.",
                   "Unplug the radio, plug it back in and try again. If it keeps happening, try "
                   "another USB port or cable.",
                   UNCHANGED, buttons=["retry", "diagnostics"], detail=detail)
    if code == "write_unverified":
        return Msg("E-R4", "The write didn't take.",
                   "The radio still differs from the codeplug after writing%s. Write again; if "
                   "that fails too, open a codeplug file you know is good and write that."
                   % _where(e, detail),
                   "Don't use this radio until this is fixed.", severe=True,
                   buttons=["write_again"], detail=detail)
    if code == "keys_refused":
        return Msg("E-K6", "This radio didn't accept the key table.",
                   "It may not be an MD-UV390 Plus. Only the Plus takes AES keys (Universal "
                   "privacy); Basic and Enhanced privacy work without them.",
                   "Nothing was written. The radio's keys are as they were.", detail=detail)
    if code == "transfer_failed":
        if radio in ("keys_unknown",):
            return Msg("E-K4", "The connection dropped while sending keys.",
                       "Encrypted channels may not work. Write the keys again before using the "
                       "radio.",
                       "The radio's keys are unknown.", severe=True,
                       buttons=["write_keys_again"], detail=detail)
        if radio in ("codeplug_incomplete",):
            return Msg("E-R5", "The connection dropped while writing.",
                       "Write again, or write a codeplug file you know is good.",
                       "The radio's codeplug is now incomplete. Don't unplug it again.",
                       severe=True, buttons=["write_again"], detail=detail)
        if radio in ("codeplug_unverified",):
            return Msg("E-R5", "The connection dropped while checking the write.",
                       "The codeplug was written but could not be read back to confirm it. "
                       "Read the radio, or write again.",
                       "The radio's contents are unconfirmed.", severe=True,
                       buttons=["write_again"], detail=detail)
        if radio in ("codeplug_written", "keys_written"):
            return Msg("E-R5", "The connection dropped after the write.",
                       "The write finished and was verified%s." %
                       ("" if radio == "codeplug_written" else " as far as keys can be"),
                       "The radio holds what you asked for.", detail=detail)
        if radio == "unchanged":
            return Msg("E-R5", "The connection dropped.",
                       "Reconnect the radio and try again.", NOTHING,
                       buttons=["retry"], detail=detail)
        return _unknown_state(res, "The connection dropped.", detail)
    if code == "keyfile_invalid":
        return Msg("E-K1", "That file isn't a CPS key file.",
                   detail or "Expected 20480 bytes in the CPS .dec format.", NOTHING, detail=detail)
    if code == "conf_invalid":
        where = _location(e)
        return Msg("E-C1", "%s%s" % (where + ": " if where else "", detail or "The codeplug has an error."),
                   "Fix the cell to continue.", NOTHING, detail=detail)
    if code == "key_slot_empty":
        return Msg("E-C2", "Channel '%s' uses key slot %s, which is empty in the current key set."
                   % (e.get("name", "?"), e.get("slot", "?")),
                   "Pick a filled slot, or add a key to slot %s." % e.get("slot", "?"),
                   NOTHING, buttons=["goto", "open_keys"], detail=detail)
    if code == "ledger_failed" and not (radio == "keys_written" or
                                        res.command.label == "write-keys"):
        return Msg("E-S5", "The ledger couldn't be written.",
                   "Check disk space and permissions on the fleet folder, then try again. (%s)"
                   % (detail or "unknown reason"),
                   "No radio was touched.", detail=detail)
    if code == "ledger_failed":
        return Msg("E-K5", "The keys were written, but the record couldn't be saved.",
                   "Don't write the keys again. Fix the problem, then click Record now. (%s)"
                   % (detail or "unknown reason"),
                   "The radio holds the new keys.", severe=True,
                   buttons=["record_now", "copy_line"], detail=detail)
    if code == "unit_unreadable":
        return Msg("E-K3", "Couldn't identify the radio.",
                   "Reconnect it and try again.", NOTHING, buttons=["retry"], detail=detail)
    if code == "image_invalid":
        return Msg("E-R7", "That file isn't a codeplug for this radio.",
                   detail or "It isn't an 851968-byte MD-UV390 codeplug.", NOTHING, detail=detail)
    if code == "io_error":
        return Msg("E-S4", "A file couldn't be read or written.",
                   detail or "", NOTHING if res.command.radio else "", detail=detail)
    if code == "conf_unreadable":
        return Msg("E-C4", "Can't read this codeplug.", detail,
                   NOTHING if res.command.radio else "", detail=detail)
    if res.command.radio and radio != "unchanged":
        return _unknown_state(res, "The programming engine failed (%s)." % code, detail)
    return Msg("E-X", "The programming engine failed (%s)." % code,
               detail or "No reason was given. Copy diagnostics and report it.",
               NOTHING if res.command.radio else "", buttons=["diagnostics"], detail=detail)


def _unknown_state(res, title, detail):
    """A run that stopped without saying what the radio holds. Never shown as
    'nothing was written' once the run had started writing."""
    label = res.command.label
    if label == "write-keys" and (res.reached("keys") or res.radio_state == "keys_unknown"):
        return Msg("E-K4", title, "Write the keys again before using this radio.",
                   "The radio's keys are unknown.", severe=True,
                   buttons=["write_keys_again"], detail=detail)
    if label in ("write-codeplug", "write-image") and res.reached("erase", "write", "verify"):
        return Msg("E-R5", title, "Write again, or write a codeplug file you know is good.",
                   "The radio's codeplug may now be incomplete. Don't use this radio until "
                   "a write completes.", severe=True,
                   buttons=["write_again"], detail=detail)
    if not res.reached("erase", "write", "keys"):
        return Msg("E-X", title, detail or "Copy diagnostics and report it.", NOTHING,
                   buttons=["retry", "diagnostics"], detail=detail)
    return Msg("E-X", title, detail or "Copy diagnostics and report it.",
               "What the radio holds now is not known.", severe=True,
               buttons=["diagnostics"], detail=detail)


def _quoted(text):
    m = re.search(r"'([^']+)'", text or "")
    return m.group(1) if m else None


def _where(e, detail):
    n = e.get("bytes") or e.get("differ")
    first = e.get("first")
    if n and first is not None:
        return " in %s bytes (first at 0x%05X)" % (n, int(first))
    return ""


def _location(e):
    sec = e.get("section")
    if not sec:
        return ""
    names = {"Digital": "Channels (digital)", "Analog": "Channels (analog)", "Zone": "Zones",
             "Scanlist": "Scan lists", "Contact": "Contacts", "Grouplist": "Group lists",
             "Message": "Messages", "General": "General", "EmergencySystem": "Emergency system",
             "DTMFSystem": "DTMF system", "DTMFEncode": "DTMF encode", "DTMFDecode": "DTMF decode"}
    s = names.get(sec, sec)
    if sec == "General":
        return "%s, %s" % (s, e.get("column", ""))
    return "%s row %s%s" % (s, e.get("id", e.get("row", "?")),
                            (", " + e["column"]) if e.get("column") else "")


BUTTON_TEXT = {
    "retry": "Try again", "fix_usb": "USB access…", "diagnostics": "Copy diagnostics",
    "write_again": "Write again",
    "write_keys_again": "Write keys again", "goto": "Go to channel", "open_keys": "Open Keys",
    "record_now": "Record now", "copy_line": "Copy line",
}


def show(parent, msg):
    """Show a Msg; returns the action name clicked, or None for Close."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical if msg.severe else QMessageBox.Icon.Warning)
    box.setWindowTitle("TYTcps")
    box.setText("<b>%s</b>" % _esc(msg.title))
    body = _esc(msg.body)
    if msg.state:
        body += "<br><br>" + ("<b>%s</b>" if msg.severe else "%s") % _esc(msg.state)
    box.setInformativeText(body)
    if msg.detail:
        box.setDetailedText("%s\n\n(%s)" % (msg.detail, msg.id))
    actions = {}
    for b in msg.buttons:
        btn = box.addButton(BUTTON_TEXT.get(b, b), QMessageBox.ButtonRole.ActionRole)
        actions[btn] = b
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    return actions.get(box.clickedButton())


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
