# GeneralsOnline-MacLocales

Per-language voice, movie and texture packs for Generals Online on macOS. Assembled from the
Steam language depots of Zero Hour, published as release zips on GitHub; the launcher offers a
pack next to its Game Language setting and only when a game install is present.

Text is not here: every language's `generals.csf` and INI files ship with
[GeneralsOnline-MacPatch](https://github.com/Okladnoj/GeneralsOnline-MacPatch).

## How the engine finds a localized file

Archives of the Zero Hour folder, of the Generals folder and of an active mod form one directory
tree; the mod sits on top, Zero Hour before Generals. A sound resolves as
`Data\Audio\<Sounds|Speech>\<Language>\<file>`, then without a language, then as
`…\English\<file>` — each step across the whole tree. Movies follow
`Data/<Language>/Movies` → `Data/English/Movies` → `Data/Movies`.

So a pack carries only what differs from English, and it never replaces anything: it adds
`<Language>` paths next to the English ones, and the `Language` key of `Options.ini` picks them.
None of this takes part in the INI CRC or in game logic.

## Layout

```
GO_Mac_Locale_<Language>/
├── locale.json                    language, packageVersion, what the pack holds
├── Assets/                        → Zero Hour   (the folder containing INIZH.big)
│   ├── GOLocale<Language>ZH.big   sounds, speech, textures
│   └── Data/<Language>/Movies/    campaign movies
└── AssetsGenerals/                → Generals    (the folder with INI.big and no INIZH.big)
    └── GOLocale<Language>.big     sounds, speech, textures
```

Zero Hour also reads the Generals archives, so a Zero Hour player needs both halves: most unit
replies of the original factions live in the Generals archives.

The archive names are our own (`GOLocale…`), never EA's: the launcher tells an installed pack
from a native language install (`Speech<Language>ZH.big` from a localized disc or depot).

## Contents

| Language | Zero Hour voices | Generals voices | Movies | Zip |
|---|---|---|---|---|
| German | own (new ZH units: censored robot voice) | uncensored, 2003 first edition | 39 | 791 MB |
| French | own | own | 19 | 799 MB |
| Spanish | — | own | 4 | 363 MB |
| Italian | — | own | 4 | 358 MB |
| Korean | — | — | 17 | 270 MB |
| Chinese | — | — | 17 | 270 MB |
| Polish | — | — | 2 | 3 MB |
| Brazilian | — | — | 4 | 42 MB |

"—" means the depot holds English files under that language's path; they are left out and the
engine plays English. Every pack also carries the localized UI textures that differ from English.

What is left out of every depot: `W3D<Language>ZH.big` (German censorship models), the language's
text (the patch has its own), splash screens and documents.

### German

The German Steam depot is the censored "Generäle" edition: unit voices are processed into robot
voices. The Generals half is therefore built from the uncensored first edition of January 2003
(`sources/german_uncut/`, from the *Command & Conquer: Generals Uncensor* mod, Nexus Mods
cncgenerals #1111), and the Zero Hour half leaves out the 1771 replies that duplicate Generals
units, so lookup falls through to the uncensored ones. The 790 replies of units introduced by
Zero Hour exist only censored and stay as they are. Campaign speech is not processed.

The uncensored unit replies are recorded quieter than the English ones; assembly raises each
PCM reply to the RMS level of its English counterpart, never lowering, with peaks kept below
full scale.

The base German depot names its folders `German2`; assembly renames them to `German`, which is
what the engine looks up.

## Publishing

```sh
./download_depots.sh            # Steam depots → depots/<language>/ (steamcmd, your account)
./assemble_locales.sh           # depots + sources → GO_Mac_Locale_<Language>/
./pack_upload.sh                # zips → release v1.0, catalog → ../general_online_zh/public/api/locales.json
```

Selective: `./assemble_locales.sh german`, `./pack_upload.sh --no-upload German`.
`./assemble_locales.sh --dry-run` reports what each pack would hold without writing anything.

`depots/`, `sources/`, the trees and the zips are not committed: they are original game data.
Requires `gh` authenticated against `Okladnoj/GeneralsOnline-MacLocales`; the site is deployed
on its own.
