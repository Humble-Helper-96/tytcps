# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock CPS's pages, field by field, for the forms that edit them.

Mirrors the engine's cpsfields.c tables. The
engine owns the bytes; this module only knows each field's conf key, its
CPS label, how the conf writes its values, and where the CPS puts it on
screen. A value the engine prints as raw:0xNN has no CPS meaning: the form
shows it as it is and keeps it unless the operator picks a real value.
"""

from dataclasses import dataclass, field


@dataclass
class F:
    key: str                 # conf key (General scalar) or column name
    label: str               # the CPS's own label
    kind: str                # bool, enum, num, id, ro, text
    choices: tuple = ()      # enum values as the conf writes them
    lo: int = 0              # num: range in display units (the CPS's spin limits)
    hi: int = 0
    step: int = 1            # num: the CPS's arrow step
    unit: int = 1            # num: what one stored step is worth; a value
                             # must be a multiple of it (engine: x scale)
    zero: str = None         # num: the word for 0 (Continue, Hang, -)
    single: bool = False     # only the CPS's own code maps it (firmware untested)
    tip: str = ""
    when: tuple = None       # (key, value): editable only while that scalar has that
                             # value ("!value": anything else); or a tuple of such pairs
    confirm: str = ""        # asked before a value is set (lockout risks)
    labels: tuple = ()       # enum: what the CPS shows for each choice, if not the token
    ref: str = ""            # ref: which records the choices are (see cpsforms.ref_items)
    required: bool = False   # dtmf/name: can't be empty
    choices_by: tuple = None # enum: (scalar key, {its value: choices}): the list
                             # depends on another field, as the CPS's does


SINGLE_TIP = ("Written the same way as the CPS. The firmware may ignore it.")
RO_TIP = "Shown for information. TYTcps doesn't set this: a mistake here could lock the radio."

LOCK_CONFIRM = ("The radio will ask for the Power On Password every time it's switched on. If the "
                "password is lost, the radio has to be reprogrammed over the cable.")
PROGRAM_CONFIRM = ("The radio will ask for this password before settings can be changed from its "
                   "keypad. If it's lost, the radio has to be reprogrammed over the cable.")

TZ = tuple("UTC %+d:00" % h for h in range(-12, 13))

# General Setting, as the CPS lays it out: three columns of groups.
GENERAL = [
    # left column
    ("Save", [F("Save Preamble", "Save Preamble", "bool"),
              F("Save Mode Receive", "Save Mode Receive", "bool")]),
    ("Alert Tone", [F("Disable All Tone", "Disable All Tone", "bool"),
                    F("CH Free Indication Tone", "CH Free Indication Tone", "bool"),
                    F("Talk Permit Tone", "Talk Permit Tone", "enum",
                      ("None", "Digital", "Analog", "Analog & Digital")),
                    F("Call Alert Tone Duration[s]", "Call Alert Tone Duration[s]", "num",
                      lo=0, hi=1200, step=5, unit=5, zero="Continue")]),
    ("Scan", [F("Scan Digital Hang Time[ms]", "Scan Digital Hang Time[ms]", "num", lo=500, hi=10000, step=500, unit=100),
              F("Scan Analog Hang Time[ms]", "Scan Analog Hang Time[ms]", "num", lo=0, hi=10000, step=500, unit=100)]),
    ("Lone Worker", [F("Lone Worker Response Time[min]", "Lone Worker Response Time[min]", "num", lo=1, hi=255),
                     F("Lone Worker Reminder Time[s]", "Lone Worker Reminder Time[s]", "num", lo=1, hi=255)]),
    ("Power On Password", [F("Password and Lock Enable", "Password and Lock Enable", "bool",
                             confirm=LOCK_CONFIRM),
                           F("Power On Password", "Power On Password", "pin8",
                             when=("Password and Lock Enable", "+"), confirm=LOCK_CONFIRM,
                             tip="8 digits.")]),
    ("Voice Announcement", [F("CH Voice Announcement", "CH Voice Announcement", "bool"),
                            F("Voice Announcement", "Voice Announcement", "enum",
                              ("English", "Chinese"), single=True)]),
    None,
    # middle column
    ("", [F("Name", "Radio Name", "text"),
          F("ID", "Radio ID", "text"),
          F("Monitor Type", "Monitor Type", "enum", ("Silent", "Open Squelch")),
          F("VOX Sensitivity", "VOX Sensitivity", "enum", tuple(str(n) for n in range(1, 11))),
          F("TX Preamble Duration[ms]", "TX Preamble Duration[ms]", "num", lo=0, hi=8640, step=60, unit=60),
          F("RX Low Battery Interval[s]", "RX Low Battery Interval[s]", "num", lo=0, hi=635, step=5, unit=5),
          F("Channels Hang Time[ms]", "Channels Hang Time[ms]", "num", lo=0, hi=7000, step=500, unit=100),
          # No PC Programming Password: the radio hands it to anyone who
          # asks and doesn't enforce it; only the stock CPS does (7.7). The
          # conf line passes through, so a radio keeps whatever it has.
          F("Radio Program Password", "Radio Program Password", "pin8", confirm=PROGRAM_CONFIRM,
            tip="8 digits. Empty = none."),
          F("Back Light Time[s]", "Back Light Time[s]", "enum", ("Always", "5", "10", "15")),
          F("Set Keypad Lock Time[s]", "Set Keypad Lock Time[s]", "enum", ("Manual", "5", "10", "15")),
          F("Freq/Channel Mode", "Freq/Channel Mode", "enum", ("Channel", "Freq")),
          F("Model Select A", "Model Select A", "enum", ("VFO", "MR"),
            when=("Freq/Channel Mode", "Freq")),
          F("Model Select B", "Model Select B", "enum", ("VFO", "MR"),
            when=("Freq/Channel Mode", "Freq")),
          F("Time Zone", "Time Zone", "enum", TZ),
          F("Disable All LEDs", "Disable All LEDs", "bool"),
          F("Group Call Match", "Group Call Match", "bool"),
          F("Private Call Match", "Private Call Match", "bool")]),
    ("Talkaround", [F("Group Call Hang Time[ms]", "Group Call Hang Time[ms]", "num", lo=0, hi=7000, step=500, unit=100),
                    F("Private Call Hang Time[ms]", "Private Call Hang Time[ms]", "num", lo=0, hi=7000, step=500, unit=100)]),
    ("Intro Screen", [F("Intro Screen", "Intro Screen", "enum", ("Char String", "Picture")),
                      F("Intro Line 1", "Intro Screen Line 1", "text"),
                      F("Intro Line 2", "Intro Screen Line 2", "text")]),
    None,
    # right column
    ("", [F("Radio ID 1", "Radio ID 1", "id"),
          F("Radio ID 2", "Radio ID 2", "id"),
          F("Radio ID 3", "Radio ID 3", "id"),
          F("MIC Level", "MIC Level", "enum", tuple(str(n) for n in range(1, 7))),
          F("Tx Mode", "Tx Mode", "enum", ("Last Call CH", "Last Call CH + HandCH",
                                           "Designed CH", "Designed CH + HandCH")),
          F("Front Keyboard Lock", "Front Keyboard Lock", "bool", single=True),
          F("Edit Radio ID", "Edit Radio ID", "bool"),
          F("Public Zone", "Public Zone", "bool"),
          F("Power On Voice", "Power On Voice", "bool", single=True),
          F("TX/RX LED", "TX/RX LED", "bool", single=True,
            tip="Labelled '??/???' in the CPS (TX/RX light). No visible effect on firmware "
                "S119.038.")]),
]

MENU_HANG = F("Menu Hang Time[s]", "Menu Hang Time[s]", "num", lo=0, hi=30, zero="Hang")
LONG_PRESS = F("Long Press Duration[ms]", "Long Press Duration[ms]", "num", lo=1000, hi=10000, step=250, unit=250)

# Menu Item boxes, grouped as on the CPS page: (conf item, CPS label, single source)
MENU = [
    ("Contacts", [("Call_Alert", "Call Alert", False), ("Edit_Contact", "Edit Contact", False),
                  ("Manual_Dial", "Manual Dial", False), ("New_Contact", "New Contact", True),
                  ("Remote_Monitor", "Remote Monitor", False), ("Group_Call", "Group Call", True),
                  ("Radio_Enable", "Radio Enable", False), ("Radio_Check", "Radio Check", False),
                  ("Radio_Disable", "Radio Disable", False), ("Program_Key", "Program Key", True)]),
    ("Call Log", [("Missed", "Missed", False), ("Answered", "Answered", False),
                  ("Outgoing_Radio", "Outgoing Radio", False),
                  ("Delete_All_Records", "Delete all records", True)]),
    ("Zone", [("Zone", "Zone", False), ("Edit_Zone", "Edit Zone", False),
              ("New_Zone_List", "New Zone List", False)]),
    ("Utilities", [("Talkaround", "Talkaround", False), ("Tone_or_Alert", "Tone or Alert", False),
                   ("Power", "Power", False), ("Backlight", "Backlight", False),
                   ("Intro_Screen", "Intro Screen", False), ("Keyboard_Lock", "Keyboard Lock", False),
                   ("LED_Indicator", "LED Indicator", False), ("Squelch", "Squelch", False),
                   ("Password_and_Lock", "Password and Lock", False), ("VOX", "VOX", False),
                   ("Display_Mode", "Display Mode", False), ("Program_Radio", "Program Radio", False),
                   ("Group_Call_Match", "Group Call Match", False), ("Record_Switch", "Record Switch", False),
                   ("Private_Call_Match", "Private Call Match", False), ("TX_Mode", "TX Mode", False),
                   ("Monitor", "Monitor", True), ("Select_Radio_ID", "Select Radio ID", True),
                   ("Menu_Hang_Time", "Menu Hang Time", False), ("Power_On_Voice", "Power On Voice", True)]),
    ("Scan", [("Scan", "Scan", False), ("Edit_List", "Edit List", False),
              ("New_Scan_List", "New Scan List", False)]),
]
MENU_TEXT = ("Text_Message", "Text Message", False)

# Side button functions (the CPS's keydata.ini [MD-UV390] set), conf words.
BUTTON_FUNCTIONS = (
    "Unassigned", "All_Alert_Tones_On/Off", "Emergency_On", "Emergency_Off", "Power_Select",
    "Monitor", "One_Touch_Access_1", "One_Touch_Access_2", "One_Touch_Access_3",
    "One_Touch_Access_4", "One_Touch_Access_5", "One_Touch_Access_6", "Repeater/Talkaround",
    "Scan_On/Off", "Squelch_Level", "Privacy_On/Off", "VOX_On/Off", "Zone_+",
    "Battery_Indicator", "Lone_Work_On/Off", "Record_On/Off", "Record_Playback",
    "Delete_All_Record", "1750Hz", "Switch_Up/Down_Screen", "Right_Key", "Left_Key", "Zone_-")

BUTTONS = [("Side_Button1", "Side Button1"), ("Side_Button2", "Side Button2")]

# Channel details beyond the Digital/Analog tables: (column, CPS label, kind, choices)
CHAN_DIGITAL = [
    F("Width", "Band Width", "enum", ("12.5", "20", "25")),
    F("Sq", "Squelch", "enum", tuple(str(n) for n in range(10))),
    F("RxRef", "RX Ref Frequency", "enum", ("Low", "Medium", "High")),
    F("TxRef", "TX Ref Frequency", "enum", ("Low", "Medium", "High")),
    F("Rekey", "TOT Rekey Delay[s]", "num", lo=0, hi=255),
    F("AS", "Auto Scan", "bool"),
    F("LW", "Lone Worker", "bool"),
    F("VOX", "VOX", "bool"),
    F("TA", "Allow Talkaround", "bool"),
    F("PCC", "Private Call Confirmed", "bool"),
    F("EAA", "Emergency Alarm Ack", "bool"),
    F("DCC", "Data Call Confirmed", "bool"),
    F("AI", "Allow Interrupt", "bool"),
    F("DCDM", "DCDM Switch", "bool",
      tip="With DCDM on, the channel's TOT must be 15, 30, 45 or 60 s."),
    F("Leader", "Leader/MS", "enum", ("Leader", "MS")),
    F("EmSys", "Emergency System", "ref", ref="emsystems"),
    F("InCall", "In Call Criteria", "enum", ("Always", "Follow", "TxInt")),
    F("MsgFmt", "Message Format", "enum", ("DMR", "M"), single=True),
]
CHAN_ANALOG = [
    F("RxRef", "RX Ref Frequency", "enum", ("Low", "Medium", "High")),
    F("TxRef", "TX Ref Frequency", "enum", ("Low", "Medium", "High")),
    F("Rekey", "TOT Rekey Delay[s]", "num", lo=0, hi=255),
    F("AS", "Auto Scan", "bool"),
    F("LW", "Lone Worker", "bool"),
    F("VOX", "VOX", "bool"),
    F("TA", "Allow Talkaround", "bool"),
    F("RxSig", "Rx Signaling System", "enum", ("Off", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4")),
    F("TxSig", "Tx Signaling System", "enum", ("Off", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4")),
    F("QTRev", "QT Reverse", "enum", ("180", "120", "240", "Silent"), single=True),
    F("TurnOff", "Non-QT/DQT Turn-off Freq", "enum", ("259.2", "55.2", "None")),
    F("PTTID", "Display PTT ID", "bool"),
    F("RevBurst", "Reverse Burst/Turn-off Code", "bool", single=True),
    F("Decode", "Decode 1-8", "decode"),
]
SCAN_TIMING = [
    F("Hold[ms]", "Signaling Hold Time[ms]", "num", lo=0, hi=6375, step=25, unit=25),
    F("Sample[ms]", "Priority Sample Time[ms]", "num", lo=0, hi=63750, step=250, unit=250),
]

# What a channel the engine creates holds (erase_channel, and Message Format
# DMR on a digital one, as the CPS), as the extra rows write it, so a new
# channel's details start from what the radio would get.
NEW_DIGITAL = ["12.5", "1", "Low", "Low", "0", "-", "-", "-", "-", "-", "-", "-", "-", "-",
               "MS", "-", "Always", "DMR"]
NEW_ANALOG = ["Low", "Low", "0", "-", "-", "-", "-", "Off", "Off", "180", "None", "-", "+",
              "--------"]


def all_general():
    return [f for group in GENERAL if group for f in group[1]]


# What each field does, shown when hovering over it. Sources: the DARC guide
# to the MD-380 CPS (Save, tones, Admit Criteria), the MOTOTRBO settings TYT's
# CPS copies, and the bench (6.8). Where nothing documents a field, the hint
# says so rather than guess.
HINTS = {
    # General Setting
    "Save Preamble": "Sends a short preamble before each transmission to wake radios that are in "
                     "power-save mode, so they don't miss the start of the call.",
    "Save Mode Receive": "Power-save for this radio's receiver while the channel is idle. Saves "
                         "battery (about 10%).",
    "Disable All Tone": "Turns off every beep, including the low-battery warning.",
    "CH Free Indication Tone": "A short tone when the other station stops talking and the channel "
                               "is free.",
    "Talk Permit Tone": "A tone after pressing PTT when the radio is ready to transmit (for "
                        "example synced to the repeater). Start talking after it.",
    "Call Alert Tone Duration[s]": "How long an incoming call alert rings. Continue rings until "
                                   "answered.",
    "Scan Digital Hang Time[ms]": "How long scan stays on a digital channel after activity ends "
                                  "before moving on.",
    "Scan Analog Hang Time[ms]": "How long scan stays on an analog channel after activity ends "
                                 "before moving on.",
    "Lone Worker Response Time[min]": "Lone worker: how often the user must check in. Pressing "
                                      "PTT resets the timer.",
    "Lone Worker Reminder Time[s]": "Lone worker: how long the user has to answer the check-in "
                                    "reminder before the radio sends an emergency alarm.",
    "Password and Lock Enable": "Ask for the Power On Password whenever the radio is switched "
                                "on.",
    "Power On Password": "The password the radio asks for at power-on, when Password and Lock "
                         "Enable is on.",
    "CH Voice Announcement": "The radio speaks the channel number when you change channel.",
    "Voice Announcement": "Language of the voice prompts: English or Chinese. The stock CPS only "
                          "offers English; Chinese is in its own list but never shown, so what "
                          "the radio does with it is untested.",
    "Name": "The radio's name, shown on its display. A write keeps each radio's own name unless "
            "you change it here.",
    "ID": "The radio's DMR ID. A write keeps each radio's own ID unless you change it here.",
    "Monitor Type": "What the Monitor button does: Silent opens the audio for any signal on the "
                    "channel; Open Squelch opens it fully, noise included.",
    "VOX Sensitivity": "How easily your voice keys the transmitter when VOX is on.",
    "TX Preamble Duration[ms]": "Length of the wake-up preamble sent before private calls and "
                                "data, so scanning or sleeping radios catch it.",
    "RX Low Battery Interval[s]": "How often the low-battery warning repeats.",
    "Channels Hang Time[ms]": "Undocumented. TYT doesn't say what this does, and the CPS gives no "
                              "clue beyond its Chinese label, which means \"channel hang time\".",
    "Radio Program Password": "A password the radio asks for before settings can be changed from "
                              "its keypad.",
    "Back Light Time[s]": "How long the display stays lit after a key press. Always keeps it on.",
    "Set Keypad Lock Time[s]": "Lock the keypad automatically after this many seconds. Manual "
                               "locks only when you lock it.",
    "Freq/Channel Mode": "Channel uses the programmed channels. Freq lets frequencies be entered on "
                         "the radio's keypad (VFO).",
    "Model Select A": "Whether display A starts in VFO (frequency) or MR (channel) mode. Only "
                      "used in Freq mode.",
    "Model Select B": "Whether display B starts in VFO (frequency) or MR (channel) mode. Only "
                      "used in Freq mode.",
    "Time Zone": "Time zone for the radio's clock.",
    "Disable All LEDs": "Turns off the red/green TX/RX light on top of the radio.",
    "Group Call Match": "Ticked: hear only group calls in the channel's RX group list. Unticked: "
                        "hear every group on the timeslot.",
    "Private Call Match": "Ticked: hear only private calls to this radio's ID. Unticked: hear "
                          "private calls to any ID.",
    "Group Call Hang Time[ms]": "After a group call, how long pressing PTT replies to that group "
                                "instead of the channel's contact.",
    "Private Call Hang Time[ms]": "After a private call, how long pressing PTT replies to that "
                                  "caller.",
    "Intro Screen": "What the radio shows at power-on: the two text lines or the picture.",
    "Intro Line 1": "First line of the power-on screen.",
    "Intro Line 2": "Second line of the power-on screen.",
    "Radio ID 1": "Extra DMR IDs the radio can switch to (Select Radio ID in its menu).",
    "Radio ID 2": "Extra DMR IDs the radio can switch to (Select Radio ID in its menu).",
    "Radio ID 3": "Extra DMR IDs the radio can switch to (Select Radio ID in its menu).",
    "MIC Level": "Microphone gain.",
    "Tx Mode": "Which channel PTT transmits on: the last channel a call came in on, or the "
               "selected (designated) channel. \"+ HandCH\" also follows a channel changed by "
               "hand.",
    "Front Keyboard Lock": "Undocumented. TYT doesn't say what this does, and the CPS gives no clue "
                           "beyond its Chinese label, which means \"front panel lock\".",
    "Edit Radio ID": "Whether the radio's ID can be changed from its own menu.",
    "Public Zone": "Undocumented. TYT doesn't say what this does, and the CPS gives no clue beyond "
                   "its Chinese label, which means \"shared zone\".",
    "Power On Voice": "A voice greeting at power-on. No effect on firmware S119.038.",
    "Menu Hang Time[s]": "How long the radio's menu stays open without a key press. Hang keeps it "
                         "open.",
    "Long Press Duration[ms]": "How long a side button must be held to count as a long press.",
    # channel details (digital and analog)
    "Width": "Channel bandwidth: 12.5 kHz, or 20/25 kHz for wide analog channels.",
    "Sq": "Squelch level: higher needs a stronger signal to open.",
    "RxRef": "Fine adjustment of the receive reference frequency. Leave at Low unless the radio "
             "is off frequency.",
    "TxRef": "Fine adjustment of the transmit reference frequency. Leave at Low unless the radio "
             "is off frequency.",
    "Rekey": "After the transmit timer (TOT) cuts you off, seconds before you can transmit "
             "again.",
    "AS": "Start scanning the channel's scan list automatically when this channel is selected.",
    "LW": "Use the lone worker check-in on this channel.",
    "VOX": "Allow voice-activated transmit on this channel.",
    "TA": "Allow talkaround (transmit on the receive frequency, bypassing the repeater).",
    "PCC": "Private calls on this channel wait for the other radio to answer before you talk.",
    "EAA": "Emergency alarms sent on this channel must be acknowledged.",
    "DCC": "Data (text) sent on this channel waits for confirmation.",
    "AI": "Allow another radio to interrupt this one while it transmits.",
    "DCDM": "Dual Capacity Direct Mode: two simultaneous calls on one simplex frequency, one per "
            "timeslot.",
    "Leader": "With DCDM: whether this radio sets the timing (Leader) or follows it (MS).",
    "EmSys": "Which Digit Emergency System this channel uses.",
    "InCall": "When you can transmit during a call: Always, Follow Admit Criteria, or TX "
              "Interrupt.",
    "MsgFmt": "Text message format: DMR standard, or M (Motorola style).",
    "RxSig": "Signaling system decoded on receive (DTMF).",
    "TxSig": "Signaling system sent on transmit (DTMF).",
    "QTRev": "Phase shift of the CTCSS tone at the end of a transmission, to cut the squelch "
             "tail.",
    "TurnOff": "Tone sent at the end of a transmission on a channel without CTCSS/DCS, to close "
               "the other radios' squelch.",
    "PTTID": "Show the caller's PTT ID on the display.",
    "RevBurst": "Send a reverse burst (CTCSS) or turn-off code (DCS) at the end of a "
                "transmission, to cut the squelch tail.",
    "Decode": "Which DTMF decode entries are active on this channel.",
    "Hold[ms]": "How long scan stays on a channel to check for signaling before moving on.",
    "Sample[ms]": "How often scan checks the priority channels while on another channel.",
}

for _f in all_general() + [MENU_HANG, LONG_PRESS] + CHAN_DIGITAL + CHAN_ANALOG + SCAN_TIMING:
    _h = HINTS.get(_f.key)
    if _h and _h not in _f.tip:
        _f.tip = _h + ("\n\n" + _f.tip if _f.tip else "")

MENU_TIP = "Ticked: \"%s\" appears in the radio's menu."
BUTTON_TIP = "What this side button does on a %s press."


# ---------------------------------------------------------------------------
# Digit Emergency System, DTMF Signaling and VFO Mode (7.6). Settled by the
# files the CPS saved and, where those could not reach, by the CPS
# program itself.
# ---------------------------------------------------------------------------

# The Digit Emergency System page's own settings (General scalars in the conf).
EMERGENCY = [
    F("Remote Monitor Duration[s]", "Remote Monitor Duration[s]", "num", lo=10, hi=120, step=10,
      unit=10),
    F("Tx Sync Wakeup TOT[ms]", "Tx Sync Wakeup TOT[ms]", "num", lo=125, hi=375, step=25, unit=25),
    F("Tx Wakeup Message Limit", "Tx Wakeup Message Limit", "enum", ("1", "2", "3", "4")),
    F("Radio Disable Decode", "Radio Disable Decode", "bool"),
    F("Remote Monitor Decode", "Remote Monitor Decode", "bool"),
    F("Emergency Remote Monitor Decode", "Emergency Remote Monitor Decode", "bool"),
]

# One emergency system: the EmergencySystem row's columns 1-8.
EMSYS = [
    F("Name", "System Name", "name", required=True),
    F("AlarmType", "Alarm Type", "enum", ("Disabled", "Regular", "Silent", "Silent_w/Voice"),
      labels=("Disabled", "Regular", "Silent", "Silent w/Voice")),
    F("AlarmMode", "Alarm Mode", "enum",
      ("Emergency_Alarm", "Emergency_Alarm_w/Call", "Emergency_Alarm_w/Voice_To_Follow"),
      labels=("Emergency Alarm", "Emergency Alarm w/Call", "Emergency Alarm w/Voice To Follow")),
    F("TxInt", "Tx Interrupt", "bool"),
    F("Impolite", "Impolite Retries", "num", lo=1, hi=15),
    F("Polite", "Polite Retries", "enum", tuple(str(n) for n in range(15)) + ("Infinite",)),
    F("HotMic[s]", "Hot Mic Duration[s]", "num", lo=10, hi=120, step=10, unit=10),
    F("Revert", "Revert Channel", "ref", ref="revert"),
]

PTT_ID = ("None", "Pre_Only", "Post_Only", "Pre_&_Post")

# One DTMF system (DTMF-1..4): the DTMFSystem row's columns 1-13.
DTMF_SYSTEM = [
    F("FirstDelay[ms]", "First Digit Delay[ms]", "num", lo=100, hi=2550, step=10, unit=10),
    F("FirstTime[ms]", "First Digit Time[ms]", "num", lo=30, hi=2550, step=10, unit=10),
    F("Duration[ms]", "Digit Duration Time[ms]", "num", lo=30, hi=2550, step=10, unit=10),
    F("Interval[ms]", "Digit Interval Time[ms]", "num", lo=30, hi=2550, step=10, unit=10),
    F("StarHash[ms]", "*# Digit Time[ms]", "num", lo=0, hi=2550, step=10, unit=10),
    F("DKey[ms]", "D Key Assignment[ms]", "num", lo=10, hi=2550, step=10, unit=10, zero="D_Key"),
    F("NextSeq[s]", "Next Sequence Decode[s]", "tenths", lo=2, hi=255),
    F("AutoReset[s]", "Auto Reset Time[s]", "num", lo=1, hi=255),
    F("SideTone", "DTMF Side Tone", "bool"),
    F("PTTID", "PTT ID", "enum", PTT_ID, labels=("None", "Pre Only", "Post Only", "Pre & Post")),
    F("GroupCode", "Group Code", "enum", ("None", "A", "B", "C", "D", "*", "#")),
    F("KeyUp", "KeyUp Encode", "dtmf"),
    F("KeyDown", "KeyDown Encode", "dtmf"),
]
DTMF_ENCODE = F("Code", "Encode", "dtmf")
DTMF_DECODE = [
    F("ID", "DTMF ID", "dtmf"),
    F("Response", "Response Type", "enum", ("Kill", "Active")),
    F("DecodeType", "Decode Type", "enum", ("None", "Sel_Call"), labels=("None", "Sel Call")),
    F("ACK", "ACK", "ref", ref="encodes"),
    F("ACKDelay[ms]", "ACK Delay Time[ms]", "num", lo=50, hi=12750, step=50, unit=50, zero="Off"),
    F("Revert", "Revert CH", "ref", ref="decode_revert"),
]

STEPS = ("2.5", "5", "6.25", "8.33", "10", "12.5", "20", "25", "30", "50")


def vfo_fields(v):
    """VFO A or B (v = "A" or "B") as the CPS's VFO page lays it out: groups of
    (title, fields). Keys are the conf's "VFO A ..." scalars."""
    p = "VFO %s " % v
    digital = (p + "Channel Mode", "Digital")
    analog = (p + "Channel Mode", "Analog")

    def f(key, *a, **k):
        return F(p + key, key, *a, tip=HINTS_76.get(key, ""), **k)
    return [
        ("Digital/Analog Data", [
            f("Channel Mode", "enum", ("Analog", "Digital")),
            f("Band Width", "enum", ("12.5", "20", "25"), labels=("12.5kHz", "20kHz", "25kHz")),
            f("Squelch", "enum", tuple(str(n) for n in range(10))),
            f("RX Ref Frequency", "enum", ("Low", "Medium", "High")),
            f("TX Ref Frequency", "enum", ("Low", "Medium", "High")),
            f("TOT[s]", "num", lo=15, hi=555, step=15, unit=15, zero="Infinite"),
            f("TOT Rekey Delay[s]", "num", lo=0, hi=255),
            f("Power", "enum", ("Low", "Middle", "High")),
            f("RX Frequency(MHz)", "freq"),
            f("TX Frequency(MHz)", "freq"),
            # As the CPS: Correct CTCSS/CDCSS on an analog VFO, Color Code
            # on a digital one (and back to Always when the mode changes).
            f("Admit Criteria", "enum", ("Always", "Channel Free", "Correct CTCSS/CDCSS", "Color Code"),
              choices_by=(p + "Channel Mode",
                          {"Analog": ("Always", "Channel Free", "Correct CTCSS/CDCSS"),
                           "Digital": ("Always", "Channel Free", "Color Code")})),
            f("Step[kHz]", "enum", STEPS, labels=tuple(s + "K" for s in STEPS)),
            f("Auto Scan", "bool"),
            f("Rx Only", "bool"),
            f("Lone Worker", "bool"),
            f("VOX", "bool"),
            f("Allow Talkaround", "bool"),
            f("Scan List", "ref", ref="scanlists"),
        ]),
        ("Digital Data", [
            f("Private Call Confirmed", "bool", when=digital),
            f("Emergency Alarm Ack", "bool", when=digital),
            f("Data Call Confirmed", "bool", when=digital),
            f("Allow Interrupt", "bool", when=digital),
            f("DCDM Switch", "bool", when=digital),
            f("Leader/MS", "enum", ("Leader", "MS"), when=digital),
            f("Emergency System", "ref", ref="emsystems", when=digital),
            f("Contact Name", "ref", ref="contacts", when=digital),
            f("Group List", "ref", ref="grouplists", when=digital),
            f("Color Code", "enum", tuple(str(n) for n in range(16)), when=digital),
            f("Repeater Slot", "enum", ("1", "2"), when=digital),
            f("In Call Criteria", "enum", ("Always", "Follow", "TxInt"),
              labels=("Always", "Follow Admit Criteria", "TX Interrupt"), when=digital),
            f("Privacy", "enum", ("None", "Basic", "Enhanced", "Universal"), when=digital),
            f("Privacy No.", "enum", tuple(str(n) for n in range(1, 17)),
              when=(digital, (p + "Privacy", "!None"))),
            f("Message Format", "enum", ("DMR", "M"), labels=("DMR Format", "M Format"),
              single=True, when=digital),
        ]),
        ("Analog Data", [
            f("CTCSS/DCS Dec", "tone", when=analog),
            f("CTCSS/DCS Enc", "tone", when=analog),
            f("Rx Signaling System", "enum", ("Off", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4"), when=analog),
            f("Tx Signaling System", "enum", ("Off", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4"), when=analog),
            f("Decode", "decode", when=analog),
            f("QT Reverse", "enum", ("180", "120", "240", "Silent"), single=True, when=analog),
            f("Non-QT/DQT Turn-off Freq", "enum", ("259.2", "55.2", "None"),
              labels=("259.2Hz", "55.2Hz", "None"), when=analog),
            f("Reverse Burst/Turn-off Code", "bool", single=True, when=analog),
            f("Display PTT ID", "bool", when=analog),
        ]),
    ]


HINTS_76 = {
    # Digit Emergency System
    "Remote Monitor Duration[s]": "How long this radio's microphone stays open when another radio "
                                  "remotely monitors it.",
    "Tx Sync Wakeup TOT[ms]": "How long the radio waits for the repeater to wake up before giving up "
                              "on an emergency transmission.",
    "Tx Wakeup Message Limit": "How many times the radio tries to wake the repeater for an emergency.",
    "Radio Disable Decode": "Let another radio disable (stun) this one over the air.",
    "Remote Monitor Decode": "Let another radio open this one's microphone remotely to listen in.",
    "Emergency Remote Monitor Decode": "Let another radio open this one's microphone remotely "
                                       "during an emergency.",
    "Name": "The emergency system's name. Channels pick a system by number.",
    "AlarmType": "What the radio does in an emergency: Regular sounds and shows the alarm, Silent "
                 "shows nothing on this radio, Silent w/Voice keeps it silent but opens the microphone.",
    "AlarmMode": "Send only the alarm, the alarm and then a call, or the alarm followed by voice.",
    "TxInt": "Interrupt another radio's transmission to send the emergency.",
    "Impolite": "How many times the alarm is sent without waiting for a free channel.",
    "Polite": "How many times the alarm is sent waiting for a free channel first. Infinite keeps "
              "trying.",
    "HotMic[s]": "How long the microphone stays open after an emergency alarm with voice.",
    "Revert": "The channel the radio switches to in an emergency. Selected stays on the current "
              "channel.",
    # DTMF
    "FirstDelay[ms]": "Pause after keying up before the first DTMF digit.",
    "FirstTime[ms]": "How long the first DTMF digit sounds.",
    "Duration[ms]": "How long each following DTMF digit sounds.",
    "Interval[ms]": "Pause between DTMF digits.",
    "StarHash[ms]": "How long * and # sound.",
    "DKey[ms]": "How long the D digit sounds. D Key sends it like the other digits.",
    "NextSeq[s]": "Gap after which a received DTMF sequence counts as finished.",
    "AutoReset[s]": "How long after a decoded call the radio goes back to normal.",
    "SideTone": "Play the DTMF tones in this radio's speaker while sending them.",
    "PTTID": "Send the KeyUp code when PTT is pressed (Pre), the KeyDown code when it is released "
             "(Post), or both.",
    "GroupCode": "The DTMF digit that marks a group call.",
    "KeyUp": "DTMF digits sent when PTT is pressed. 0-9, A-D, * and #, up to 30.",
    "KeyDown": "DTMF digits sent when PTT is released. 0-9, A-D, * and #, up to 30.",
    "Code": "DTMF digits for this encode entry. 0-9, A-D, * and #, up to 30.",
    "ID": "The DTMF code this decode entry answers to. 0-9, A-D, * and #, up to 30.",
    "Response": "What a match does: Kill disables the radio, Active wakes it up again.",
    "DecodeType": "None, or Sel Call to treat a match as a selective call.",
    "ACK": "The encode entry the radio sends back as an acknowledgement.",
    "ACKDelay[ms]": "Pause before the acknowledgement is sent.",
    # VFO
    "Channel Mode": "Whether this VFO is analog or digital.",
    "Band Width": "Bandwidth: 12.5 kHz, or 20/25 kHz for wide analog.",
    "Squelch": "Squelch level: higher needs a stronger signal to open.",
    "RX Ref Frequency": "Fine adjustment of the receive reference frequency. Leave at Low unless "
                        "the radio is off frequency.",
    "TX Ref Frequency": "Fine adjustment of the transmit reference frequency. Leave at Low unless "
                        "the radio is off frequency.",
    "TOT[s]": "Transmit time limit. Infinite has none. With DCDM on (digital): 15, 30, 45 or 60 s.",
    "TOT Rekey Delay[s]": "After the transmit time limit cuts you off, seconds before you can "
                          "transmit again.",
    "Power": "Transmit power.",
    "RX Frequency(MHz)": "Receive frequency, 136-174 or 400-480 MHz.",
    "TX Frequency(MHz)": "Transmit frequency, 136-174 or 400-480 MHz.",
    "Admit Criteria": "When you may transmit: always, only on a free channel, or only with the "
                      "right tone (analog) or color code (digital).",
    "Step[kHz]": "How far the frequency moves for each turn of the knob or arrow press.",
    "Auto Scan": "Start scanning the scan list automatically on this VFO.",
    "Rx Only": "Receive only: PTT does nothing.",
    "Lone Worker": "Use the lone worker check-in on this VFO.",
    "VOX": "Allow voice-activated transmit.",
    "Allow Talkaround": "Allow talkaround (transmit on the receive frequency).",
    "Scan List": "The scan list used when scanning from this VFO.",
    "Private Call Confirmed": "Private calls wait for the other radio to answer before you talk.",
    "Emergency Alarm Ack": "Emergency alarms sent here must be acknowledged.",
    "Data Call Confirmed": "Data (text) sent here waits for confirmation.",
    "Allow Interrupt": "Allow another radio to interrupt this one while it transmits.",
    "DCDM Switch": "Dual Capacity Direct Mode: two calls on one simplex frequency, one per timeslot. "
                   "With it on, TOT must be 15, 30, 45 or 60 s.",
    "Leader/MS": "With DCDM: whether this radio sets the timing (Leader) or follows it (MS).",
    "Emergency System": "Which Digit Emergency System this VFO uses.",
    "Contact Name": "The contact PTT calls.",
    "Group List": "The RX group list: which groups this VFO hears.",
    "Color Code": "Digital color code, 0-15. Must match the repeater's.",
    "Repeater Slot": "Timeslot 1 or 2.",
    "In Call Criteria": "When you can transmit during a call: always, following the admit "
                        "criteria, or interrupting.",
    "Privacy": "Encryption type. Universal uses the key set written from the Keys tab.",
    "Privacy No.": "Which key. Enhanced has 8, the others 16.",
    "Message Format": "Text message format: DMR standard, or M (Motorola style).",
    "CTCSS/DCS Dec": "Tone or code needed to open the squelch. None hears everything.",
    "CTCSS/DCS Enc": "Tone or code sent with each transmission.",
    "Rx Signaling System": "DTMF system decoded on receive.",
    "Tx Signaling System": "DTMF system sent on transmit.",
    "Decode": "Which DTMF decode entries are active.",
    "QT Reverse": "Phase shift of the CTCSS tone at the end of a transmission, to cut the squelch "
                  "tail.",
    "Non-QT/DQT Turn-off Freq": "Tone sent at the end of a transmission without CTCSS/DCS, to close "
                                "the other radios' squelch.",
    "Reverse Burst/Turn-off Code": "Send a reverse burst (CTCSS) or turn-off code (DCS) at the end "
                                   "of a transmission.",
    "Display PTT ID": "Show the caller's PTT ID on the display.",
}

for _f in EMERGENCY + EMSYS + DTMF_SYSTEM + [DTMF_ENCODE] + DTMF_DECODE:
    _h = HINTS_76.get(_f.key)
    if _h and _h not in _f.tip:
        _f.tip = _h + ("\n\n" + _f.tip if _f.tip else "")

