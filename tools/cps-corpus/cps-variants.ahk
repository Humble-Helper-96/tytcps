; SPDX-License-Identifier: GPL-3.0-or-later
; cps-variants.ahk - make one-field CPS variant files automatically (the golden test corpus).
; AutoHotkey v2 (portable AutoHotkey64.exe or AutoHotkey32.exe; drag this file onto it).
;
; It drives the stock CPS MD-UV390 v2.41 (English) in a Windows VM:
;   for each visible, enabled control on each page:
;     open the stock .rdt -> open the page -> change that ONE control -> Save As <name>.rdt
;     -> close the document.
; Every change is logged to variants.tsv (before/after value), and every
; page's controls (with all dropdown entries) to inventory.tsv.
;
; It only uses File > Open / Save As and the Edit menu's pages. It never uses
; the Program menu (no Read/Write data), so no radio is involved. Keep the
; radio unplugged anyway.
;
; Before running: put a codeplug the CPS saved (stock.rdt) next to this script,
; set DIGITAL_CH and ANALOG_CH below to a digital and an analog channel in it,
; start the CPS, set it to English
; (Setting > Englsih), and close any open codeplug. Don't touch the mouse or
; keyboard while it runs; press Esc to stop it.
#Requires AutoHotkey v2.0
#SingleInstance Force
SetTitleMatchMode 1
SetControlDelay 40
SetWinDelay 60
Esc::ExitApp

; ---- settings --------------------------------------------------------------
STOCK := A_ScriptDir "\stock.rdt"                   ; the starting codeplug, next to this script
OUT   := A_ScriptDir "\variants\"                  ; output folder, made next to this script
DIGITAL_CH := "Channel 1"   ; a digital channel in stock.rdt, as the CPS lists it
ANALOG_CH  := "Channel 2"   ; an analog channel in stock.rdt
SPARE_CH   := "Channel 3"   ; an analog channel the extra round makes digital
MODE  := "smoke"    ; "smoke": baseline + inventory + 3 variants, to check it works
                    ; "all":   everything (about 315 files, roughly half an hour)
                    ; "extra": only the second-round files (EXTRA below), a minute
CPS   := "CPS MD-UV380"                           ; start of the CPS window title
; ----------------------------------------------------------------------------

; Pages: [code, Edit-menu item, channel name to show (Channel Information only)]
PAGES := [
    ["GEN", "General Setting", ""],
    ["MNU", "Menu Item", ""],
    ["BTN", "Buttons Definitions", ""],
    ["SCN", "Scan List", ""],
    ["CHD", "Channel Information", DIGITAL_CH],
    ["CHA", "Channel Information", ANALOG_CH],
    ["EMG", "Digit Emergency System", ""],
    ["VFO", "VFO Mode", ""],
    ["DTM", "DTMF Signaling", ""]
]

; Controls left out of the one-at-a-time run (done as special variants below,
; or already settled and risky to step through: frequencies, privacy, lists).
SKIP := Map(
    "GEN", [1111, 1155, 1166, 1172, 1185, 1187, 1191],
    "CHD", [2000, 2042, 2044, 2015, 2017, 2036, 2040, 2039, 2045, 2046, 2048],
    "CHA", [2000, 2042, 2044, 2015, 2017, 2036, 2040, 2039, 2045, 2046, 2048]
)

if !DirExist(OUT)
    DirCreate(OUT)
if !FileExist(STOCK) {
    MsgBox("STOCK not found:`n" STOCK)
    ExitApp
}
if !WinExist(CPS) {
    MsgBox("Start the CPS first (window title starting '" CPS "').")
    ExitApp
}
PID := WinGetPID(CPS)
LOGFILE := OUT "variants.tsv"
INVFILE := OUT "inventory.tsv"
if !FileExist(LOGFILE)
    FileAppend("file`tpage`tid`tclass`taction`tbefore`tafter`tnote`n", LOGFILE, "UTF-8")
FileAppend("page`tid`tclass`tkind`tvalue`titems`n", INVFILE, "UTF-8")

CloseAll()
work := []
if (MODE != "extra") {

; 0. Baseline: the stock file saved again with no change.
Status("Baseline: stock re-save")
OpenFile(STOCK)
SaveAs("S0_stock_resaved")
CloseAll()

; 1. Inventory: what each page shows, with every dropdown's entries.
for pg in PAGES {
    Status("Inventory: " pg[2] (pg[3] != "" ? " (" pg[3] ")" : ""))
    OpenFile(STOCK)
    child := OpenPage(pg)
    for c in Controls(child) {
        FileAppend(pg[1] "`t" c.id "`t" c.cls "`t" c.kind "`t" Esc_(Value(c)) "`t"
            . Esc_(c.kind = "combo" ? Join(ControlGetItems(c.h), " | ") : "") "`n", INVFILE, "UTF-8")
        if InSkip(pg[1], c.id) || c.kind = "spin"
            continue
        for v in Variants(c)
            work.Push([pg, c.id, v])
    }
    CloseAll()
}
}

; 2. Special variants (several controls, in order).
; [file, Edit-menu page, channel to show or "", steps]
specials := [
    ["G2_passwords", "General Setting", "", [[1111, "toggle"], [1155, "text:1234"], [1166, "text:1234"], [1172, "text:12345678"]]],
    ["G3_freq", "General Setting", "", [[1185, "pick:Freq"]]],
    ["G4_freq_modelA", "General Setting", "", [[1185, "pick:Freq"], [1187, "next"]]],
    ["G5_freq_modelB", "General Setting", "", [[1185, "pick:Freq"], [1191, "next"]]]
]
; Second round (MODE "extra"): the Power On Password needs 8 digits, and the
; CPS's own new-digital-channel defaults (an analog channel made digital).
EXTRA := [
    ["G6_poweron_password", "General Setting", "", [[1111, "toggle"], [1155, "text:12345678"]]],
    ["C3a_spare_digital", "Channel Information", SPARE_CH, [[2000, "pick:Digital"]]],
    ["C3b_spare_digital_univ1", "Channel Information", SPARE_CH,
        [[2000, "pick:Digital"], [1811, "toggle"], [2017, "pick:Universal"], [2015, "i0"]]]
]
if (MODE = "extra")
    specials := EXTRA

n := 0
for w in work {
    if (MODE = "smoke" && n >= 3)
        break
    pg := w[1], id := w[2], v := w[3]
    name := pg[1] "_" id "_" v
    if FileExist(OUT name ".rdt")
        continue                    ; already made (a rerun picks up where it stopped)
    Status("Variant " A_Index "/" work.Length ": " name)
    OpenFile(STOCK)
    child := OpenPage(pg)
    c := Find(child, id)
    if !c {
        Log(name, pg[1], id, "", v, "", "", "control not found")
        CloseAll()
        continue
    }
    before := Value(c)
    note := Apply(c, v)
    after := Value(c)
    note .= Prompt()
    Commit(child)
    SaveAs(name)
    Log(name, pg[1], id, c.cls, v, before, after, note)
    CloseAll()
    n++
}
if (MODE = "all" || MODE = "extra") {
    for s in specials {
        if FileExist(OUT s[1] ".rdt")
            continue
        Status("Special: " s[1])
        OpenFile(STOCK)
        child := OpenPage(["SPC", s[2], s[3]])
        note := ""
        for step in s[4] {
            c := Find(child, step[1])
            if !c {
                note .= " " step[1] ":not found"
                continue
            }
            b := Value(c)
            note .= Apply(c, step[2])
            note .= " " step[1] ":" b "->" Value(c) Prompt()
        }
        Commit(child)
        SaveAs(s[1])
        Log(s[1], "SPC", "", "", "special", "", "", note)
        CloseAll()
    }
}
CloseAll()
ToolTip()
MsgBox("Done (" MODE "): " n " variants. Output in " OUT)
ExitApp

; ---- what to try on each control -------------------------------------------

Variants(c) {
    switch c.kind {
    case "check":
        return ["toggle"]
    case "radio":
        return DllCall("SendMessage", "ptr", c.h, "uint", 0xF0, "ptr", 0, "ptr", 0) ? [] : ["click"]
    case "combo":
        cnt := SendMessage(0x146, 0, 0, c.h)          ; CB_GETCOUNT
        cur := SendMessage(0x147, 0, 0, c.h)          ; CB_GETCURSEL
        idx := []
        if (cnt <= 1)
            return []
        if (cnt <= 8) {
            loop cnt
                if (A_Index - 1 != cur)
                    idx.Push(A_Index - 1)
        } else {
            for i in [Mod(cur + 1, cnt), cnt - 1, cnt // 2, 0]
                if (i != cur && !HasVal(idx, i))
                    idx.Push(i)
        }
        out := []
        for i in idx
            out.Push("i" i)
        return out
    case "editspin":
        return ["up", "down"]
    case "edit":
        return ["text"]
    }
    return []
}

Apply(c, v) {
    WinActivate(CPS)
    if (v = "toggle" || v = "click") {
        SendMessage(0xF5, 0, 0, c.h)                  ; BM_CLICK
    } else if (SubStr(v, 1, 1) = "i" && IsDigit(SubStr(v, 2))) {
        ControlChooseIndex(SubStr(v, 2) + 1, c.h)
    } else if (v = "next") {
        cnt := SendMessage(0x146, 0, 0, c.h), cur := SendMessage(0x147, 0, 0, c.h)
        ControlChooseIndex(Mod(cur + 1, cnt) + 1, c.h)
    } else if (SubStr(v, 1, 5) = "pick:") {
        want := SubStr(v, 6), items := ControlGetItems(c.h)
        for i, t in items
            if InStr(t, want) {
                ControlChooseIndex(i, c.h)
                return ""
            }
        return " no entry '" want "'"
    } else if (v = "up" || v = "down") {
        if !c.spin
            return " no spin"
        ControlGetPos(, , &sw, &sh, c.spin)
        ControlClick(c.spin, , , "Left", 1, "NA x" (sw // 2) " y" (v = "up" ? 3 : sh - 3))
    } else if (v = "text" || SubStr(v, 1, 5) = "text:") {
        t := (v = "text") ? NextText(ControlGetText(c.h)) : SubStr(v, 6)
        ControlFocus(c.h)
        ControlSetText(t, c.h)
        ControlSend("{Tab}", c.h)
    }
    Sleep 150
    return ""
}

NextText(t) {
    if RegExMatch(t, "^\d+$")
        return String(Integer(t) + 1)
    return "TEST"
}

; ---- CPS mechanics ---------------------------------------------------------

OpenFile(path) {
    MenuCmd(["File", "Open"])
    dlg := WaitDialog()
    ControlSetText(path, "Edit1", dlg)
    ControlSend("{Enter}", "Edit1", dlg)
    WinWaitClose(dlg, , 10)
    Sleep 700
    Prompt()
}

SaveAs(name) {
    if FileExist(OUT name ".rdt")
        FileDelete(OUT name ".rdt")       ; no "replace?" box (its default is No)
    MenuCmd(["File", "Save As"])
    dlg := WaitDialog()
    ControlSetText(OUT name ".rdt", "Edit1", dlg)
    ControlSend("{Enter}", "Edit1", dlg)
    WinWaitClose(dlg, , 10)
    Sleep 500
    Prompt()
}

OpenPage(pg) {
    MenuCmd(["Edit", pg[2]])
    Sleep 700
    Prompt()
    child := MdiActive()
    if (pg[3] != "")
        ShowChannel(child, pg[3])
    return child
}

; Step the Channel Information page with its ->> button until the name matches.
ShowChannel(child, want) {
    c := Find(child, 2048), nxt := Find(child, 1700), first := Find(child, 1702)
    if !c || !nxt
        return
    if first
        SendMessage(0xF5, 0, 0, first.h)
    loop 3000 {
        if (Trim(ControlGetText(c.h)) = want)
            return
        last := ControlGetText(c.h)
        SendMessage(0xF5, 0, 0, nxt.h)
        Sleep 60
        if (ControlGetText(c.h) = last && A_Index > 1)
            break
    }
    MsgBox("Channel '" want "' not found on the Channel Information page.")
    ExitApp
}

; Make the CPS take the change: move focus away, then show another page.
Commit(child) {
    try ControlFocus("SysTreeView321", CPS)
    Sleep 150
    MenuCmd(["Edit", "Basic Information"])
    Sleep 400
    Prompt()
}

CloseAll() {
    ; Close every page window (the document closes with its last one), and
    ; check they are really gone before the next file is opened.
    loop 60 {
        kids := MdiChildren()
        if !kids.Length
            return
        try SendMessage(0x0010, 0, 0, kids[1], , , , , 3000)   ; WM_CLOSE, wait for it
        Sleep 150
        if WinExist("ahk_class #32770 ahk_pid " PID) {
            t := WinGetText()
            ControlClick("Button2")                   ; "No" to "save changes?"
            FileAppend("-`t-`t-`t-`tclose-prompt`t-`t-`t" Esc_(t) "`n", LOGFILE, "UTF-8")
            Sleep 250
        }
    }
    MsgBox("The CPS still has a document open after 60 tries; stopping.")
    ExitApp
}

; The visible page windows inside the CPS's MDI area.
MdiChildren() {
    out := []
    try client := ControlGetHwnd("MDIClient1", CPS)
    catch
        return out
    h := DllCall("GetWindow", "ptr", client, "uint", 5, "ptr")     ; GW_CHILD
    while h {
        ; Only visible ones: the CPS keeps a hidden window for its own blank
        ; "default1" document, which never closes.
        if DllCall("IsWindowVisible", "ptr", h)
            out.Push(h)
        h := DllCall("GetWindow", "ptr", h, "uint", 2, "ptr")      ; GW_HWNDNEXT
    }
    return out
}

MdiActive() {
    try client := ControlGetHwnd("MDIClient1", CPS)
    catch
        return 0
    return SendMessage(0x0229, 0, 0, client)          ; WM_MDIGETACTIVE
}

WaitDialog() {
    if !WinWait("ahk_class #32770 ahk_pid " PID, , 10) {
        MsgBox("No file dialog appeared.")
        ExitApp
    }
    return WinExist()
}

; A message box the CPS raised: note its text and press its default button.
Prompt() {
    Sleep 100
    if !WinExist("ahk_class #32770 ahk_pid " PID)
        return ""
    t := WinGetText()
    if InStr(t, "File name") || InStr(t, "&Open") || InStr(t, "&Save")
        return ""
    ControlSend("{Enter}", , "ahk_id " WinExist())
    Sleep 200
    return " [prompt: " RegExReplace(t, "\s+", " ") "]"
}

; Find a menu item by its text (ampersands and accelerators ignored) and send its command.
MenuCmd(names) {
    hwnd := WinExist(CPS)
    id := FindMenu(DllCall("GetMenu", "ptr", hwnd, "ptr"), names)
    if !id {
        MsgBox("Menu item not found: " Join(names, " > "))
        ExitApp
    }
    PostMessage(0x0111, id, 0, , "ahk_id " hwnd)      ; WM_COMMAND
}

FindMenu(hMenu, names) {
    loop DllCall("GetMenuItemCount", "ptr", hMenu, "int") {
        i := A_Index - 1
        buf := Buffer(1024, 0)
        DllCall("GetMenuStringW", "ptr", hMenu, "uint", i, "ptr", buf, "int", 500, "uint", 0x400)
        if (Clean(StrGet(buf, "UTF-16")) = Clean(names[1])) {
            if (names.Length = 1)
                return DllCall("GetMenuItemID", "ptr", hMenu, "int", i, "uint")
            rest := names.Clone()
            rest.RemoveAt(1)
            sub := DllCall("GetSubMenu", "ptr", hMenu, "int", i, "ptr")
            return sub ? FindMenu(sub, rest) : 0
        }
    }
    return 0
}

Clean(s) {
    s := StrReplace(s, "&")
    if (p := InStr(s, "`t"))
        s := SubStr(s, 1, p - 1)
    return Trim(RTrim(Trim(s), "."))
}

; ---- controls --------------------------------------------------------------

Controls(child) {
    out := [], spins := Map()
    for h in WinGetControlsHwnd("ahk_id " child) {
        if !DllCall("IsWindowVisible", "ptr", h) || !DllCall("IsWindowEnabled", "ptr", h)
            continue
        if (ClassOf(h) = "msctls_updown32") {
            b := SendMessage(0x046A, 0, 0, h)         ; UDM_GETBUDDY
            if b
                spins[b] := h
        }
    }
    for h in WinGetControlsHwnd("ahk_id " child) {
        if !DllCall("IsWindowVisible", "ptr", h) || !DllCall("IsWindowEnabled", "ptr", h)
            continue
        c := Describe(h, spins)
        if c.kind != ""
            out.Push(c)
    }
    return out
}

Find(child, id) {
    spins := Map()
    for h in WinGetControlsHwnd("ahk_id " child)
        if (ClassOf(h) = "msctls_updown32")
            if (b := SendMessage(0x046A, 0, 0, h))
                spins[b] := h
    for h in WinGetControlsHwnd("ahk_id " child)
        if (DllCall("GetDlgCtrlID", "ptr", h) = id && DllCall("IsWindowVisible", "ptr", h))
            return Describe(h, spins)
    return 0
}

Describe(h, spins) {
    cls := ClassOf(h), kind := ""
    style := DllCall("GetWindowLong", "ptr", h, "int", -16, "int")
    if (cls = "Button") {
        bs := style & 0xF
        kind := (bs = 2 || bs = 3 || bs = 5 || bs = 6) ? "check" : (bs = 4 || bs = 9) ? "radio" : ""
    } else if (cls = "ComboBox") {
        kind := "combo"
    } else if (cls = "Edit") {
        kind := spins.Has(h) ? "editspin" : ((style & 0x800) ? "" : "edit")   ; skip ES_READONLY
    } else if (cls = "msctls_updown32") {
        kind := "spin"
    }
    return {h: h, id: DllCall("GetDlgCtrlID", "ptr", h), cls: cls, kind: kind,
            spin: spins.Has(h) ? spins[h] : 0}
}

Value(c) {
    switch c.kind {
    case "check", "radio":
        return SendMessage(0xF0, 0, 0, c.h) ? "+" : "-"
    case "combo":
        i := SendMessage(0x147, 0, 0, c.h)
        items := ControlGetItems(c.h)
        return (i >= 0 && i < items.Length) ? i ":" items[i + 1] : String(i)
    default:
        return ControlGetText(c.h)
    }
}

ClassOf(h) {
    buf := Buffer(512, 0)
    DllCall("GetClassNameW", "ptr", h, "ptr", buf, "int", 256)
    return StrGet(buf, "UTF-16")
}

; ---- small helpers ---------------------------------------------------------

; Where the script is, shown at the top left of the screen while it works.
Status(text) {
    CoordMode("ToolTip", "Screen")
    ToolTip("cps-variants (" MODE "): " text "`nHands off; Esc stops it.", 10, 10)
}

InSkip(page, id) => SKIP.Has(page) && HasVal(SKIP[page], id)

HasVal(arr, v) {
    for x in arr
        if (x = v)
            return true
    return false
}

Join(arr, sep) {
    s := ""
    for i, x in arr
        s .= (i > 1 ? sep : "") x
    return s
}

Esc_(s) => StrReplace(StrReplace(StrReplace(s, "`t", " "), "`r", " "), "`n", " ")

Log(file, page, id, cls, action, before, after, note) {
    FileAppend(file "`t" page "`t" id "`t" cls "`t" action "`t" Esc_(before) "`t" Esc_(after)
        . "`t" Esc_(note) "`n", LOGFILE, "UTF-8")
}
