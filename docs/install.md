# Installing TYTcps

Download the Flatpak or the AppImage from the
[Releases page](https://github.com/Humble-Helper-96/tytcps/releases). Both work on Ubuntu 22.04 and Linux Mint 21
or newer.

## As a Flatpak

Linux Mint has Flatpak already; on Ubuntu, install it once with
`sudo apt install flatpak`. Then:

    flatpak install --user TYTcps-0.3.0.flatpak

The first time, it also fetches the KDE runtime from Flathub (it asks
first).

and start TYTcps from your applications menu, or with
`flatpak run io.github.Humble_Helper_96.TYTcps`.

**One more step, once per computer: the USB rule.** A Flatpak can't give
itself permission to use the programming cable, so TYTcps shows a red mark
next to "USB access rule" until it's in place. Press **Show command**, copy
the three lines into a terminal, and enter your password when asked. They
are:

    echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="df11", MODE="0660", GROUP="plugdev", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-tytcps.rules
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=0483

Then unplug the radio and plug it back in.

Your fleet folder (key sets, the ledger of which radio has which keys) is
`~/.local/share/tytcps`, the same folder a copy run from the source uses, so
switching between the two keeps your records.

## As an AppImage

Download `TYTcps-0.3.0-x86_64.AppImage`, then:

    chmod +x TYTcps-0.3.0-x86_64.AppImage
    ./TYTcps-0.3.0-x86_64.AppImage

It carries its own Python and Qt, and works on Ubuntu 22.04 and Linux Mint
21 or newer. Like the Flatpak, it needs the USB rule
put in place once: press **Show command** next to "USB access rule" and run
the three lines it shows (the same as in the Flatpak section above).

## From the source

See [Install and run](../README.md#install-and-run) in the README.

## Building the packages yourself

    flatpak install --user flathub org.flatpak.Builder
    make flatpak

This downloads the KDE runtime and the PyQt base (about 1 GB the first time),
compiles the engine inside the build, and leaves `build/TYTcps-<version>.flatpak`.

    make release      # the AppImage, built inside Ubuntu 22.04
                      # (needs docker; downloads a portable Python and PyQt6)
    make smoke        # starts it on clean Ubuntu 22.04, 24.04 and 26.04

`make appimage` builds the same on this machine directly, but the result
then needs this machine's system version or newer.
