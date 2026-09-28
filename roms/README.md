# Bring your own ROMs

omse-ai doesn't include the Spectrum's ROMs. Put them in this folder, or anywhere you like and set `OMSE_AI_ROMS` to that folder (or pass `--roms DIR`):

| File | What | Needed for |
|---|---|---|
| `48.rom` | the 48K Spectrum's ROM (BASIC) | everything |
| `128-0.rom` | the Spectrum 128's ROM 0 (the menu and 128 BASIC) | `model=128`, `boot128` |
| `128-1.rom` | the Spectrum 128's ROM 1 (48 BASIC) | `model=128`, `boot128` |

Each is 16,384 bytes. These are the names most emulators use. If you already have them for Fuse or another emulator, point `OMSE_AI_ROMS` at those.

One place to download them:

```sh
cd roms
base='https://raw.githubusercontent.com/Abdess/retrobios/main/bios/Sinclair/ZX%20Spectrum'
curl -fLO "$base/48.rom"
curl -fLO "$base/128-0.rom"
curl -fLO "$base/128-1.rom"
```

Keep the `-f`. Without it, a moved file downloads as a web page called `48.rom`: GitHub's "Page not found", with a success status. (That's how an earlier version of this recipe failed.) omse-ai refuses a ROM that's the wrong size or looks like HTML, and says so.

To check what you've got (`sha256sum` on Linux, `shasum -a 256` on a Mac):

```
d55daa439b673b0e3f5897f99ac37ecb45f974d1862b4dadb85dec34af99cb42  48.rom
3ba308f23b9471d13d9ba30c23030059a9ce5d4b317b85b86274b132651d1425  128-0.rom
8d93c3342321e9d1e51d60afcd7d15f6a7afd978c231b43435a7c0757c60b9a3  128-1.rom
```

Files ending `.rom` in this folder are ignored by git.
