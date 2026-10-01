#!/usr/bin/env python3
"""Assemble locale packs from the Steam depots in depots/.

A pack keeps only what differs from English: the engine resolves
Data\\Audio\\<Sounds|Speech>\\<Language>\\<file> first and falls back to English per file.

    ./assemble_locales.sh                  # every language
    ./assemble_locales.sh german french    # selected languages
    ./assemble_locales.sh --dry-run        # report only, write nothing
    ./assemble_locales.sh --catalog        # write the site's locales.json from built packs and zips
"""

import argparse
import array
import hashlib
import json
import math
import os
import shutil
import struct
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(ROOT, "..", "general_online_zh", "public", "api", "locales.json")
RELEASE_BASE = "https://github.com/Okladnoj/GeneralsOnline-MacLocales/releases/latest/download"
CATALOG_VERSION = 1
DEPOTS = os.path.join(ROOT, "depots")
ENGLISH_DEPOT = os.path.join(DEPOTS, "english")
GENERALS_SUBDIR = "ZH_Generals"
MOVIES_SUBDIR = "Movies"
TEXTURES_MARKER = "\\art\\textures\\"
BIG_MAGIC = b"BIGF"
BIG_INDEX_START = 0x10
BIG_TRAILER = b"L253\x00\x00\x00\x00"
COPY_CHUNK = 8 * 1024 * 1024
WAVE_FORMAT_PCM = 1
PCM16_PEAK_CEILING = 31784

LOCALES = {
    "german": {
        "language": "German",
        "packageVersion": 1,
        "generalsSource": os.path.join("sources", "german_uncut", "Command and Conquer Generals"),
        "matchEnglishLoudness": True,
        "zeroHourDefersBaseVoices": True,
        "zeroHourDropsOwnVoices": False,
    },
    "french": {"language": "French", "packageVersion": 1},
    "spanish": {"language": "Spanish", "packageVersion": 1},
    "italian": {"language": "Italian", "packageVersion": 1},
    "koreana": {"language": "Korean", "packageVersion": 1},
    "tchinese": {"language": "Chinese", "packageVersion": 1},
    "polish": {"language": "Polish", "packageVersion": 1},
    "brazilian": {"language": "Brazilian", "packageVersion": 1},
}

ARCHIVE_KINDS = (
    ("sounds", "Audio"),
    ("speech", "Speech"),
    ("textures", ""),
)


@dataclass(frozen=True)
class Entry:
    name: str
    archive: str
    offset: int
    size: int
    payload: bytes = None


@dataclass(frozen=True)
class GameOptions:
    deferred_sound_names: frozenset = frozenset()
    drop_sounds: bool = False
    match_loudness: bool = False


@dataclass
class GamePack:
    archive_name: str
    entries: list
    counts: dict
    totals: dict
    sound_names: frozenset = frozenset()
    deferred: int = 0
    louder: int = 0
    source: str = "depot"

    @property
    def size(self):
        return sum(entry.size for entry in self.entries)


@dataclass
class LocalePack:
    steam: str
    language: str
    package_version: int
    zero_hour: GamePack
    generals: GamePack
    movies: list
    movies_total: int

    @property
    def movies_size(self):
        return sum(os.path.getsize(path) for path in self.movies)

    @property
    def is_empty(self):
        return not self.zero_hour.entries and not self.generals.entries and not self.movies

    @property
    def tree(self):
        return os.path.join(ROOT, f"GO_Mac_Locale_{self.language}")


def big_entries(path):
    with open(path, "rb") as handle:
        if handle.read(4) != BIG_MAGIC:
            raise SystemExit(f"not a BIGF archive: {path}")

        handle.seek(8)
        count = struct.unpack(">I", handle.read(4))[0]
        handle.seek(BIG_INDEX_START)
        for _ in range(count):
            offset, size = struct.unpack(">II", handle.read(8))
            name = bytearray()
            while (char := handle.read(1)) not in (b"\x00", b""):
                name += char
            yield Entry(name.decode("latin-1"), path, offset, size)


def entry_digest(entry, cache):
    key = (entry.archive, entry.offset, entry.size)
    if key in cache:
        return cache[key]

    digest = hashlib.md5()
    with open(entry.archive, "rb") as handle:
        handle.seek(entry.offset)
        remaining = entry.size
        while remaining:
            chunk = handle.read(min(COPY_CHUNK, remaining))
            digest.update(chunk)
            remaining -= len(chunk)

    cache[key] = digest.digest()
    return cache[key]


def file_digest(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while chunk := handle.read(COPY_CHUNK):
            digest.update(chunk)
    return digest.digest()


def read_entry(entry):
    with open(entry.archive, "rb") as handle:
        handle.seek(entry.offset)
        return handle.read(entry.size)


def wav_data_span(payload):
    if payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return None

    wave_format = None
    position = 12
    while position + 8 <= len(payload):
        chunk_id = payload[position:position + 4]
        chunk_size = struct.unpack("<I", payload[position + 4:position + 8])[0]
        body = position + 8
        if chunk_id == b"fmt ":
            wave_format = struct.unpack("<HHIIHH", payload[body:body + 16])
        if chunk_id == b"data":
            return wave_format, body, min(chunk_size, len(payload) - body)
        position = body + chunk_size + (chunk_size & 1)
    return None


def pcm16_samples(payload):
    span = wav_data_span(payload)
    if not span:
        return None

    wave_format, start, length = span
    if not wave_format or wave_format[0] != WAVE_FORMAT_PCM or wave_format[5] != 16:
        return None

    samples = array.array("h")
    samples.frombytes(payload[start:start + length - length % 2])
    return samples, start


def rms(samples):
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def loudness_gain(samples, reference_samples):
    level = rms(samples)
    target = rms(reference_samples)
    if level == 0 or target <= level:
        return 1.0

    peak = max(abs(sample) for sample in samples)
    return min(target / level, PCM16_PEAK_CEILING / peak)


def louder_payload(entry, reference):
    payload = read_entry(entry)
    own = pcm16_samples(payload)
    english = pcm16_samples(read_entry(reference))
    if not own or not english:
        return None

    samples, start = own
    gain = loudness_gain(samples, english[0])
    if gain <= 1.0:
        return None

    scaled = array.array("h", (max(-32768, min(32767, round(sample * gain))) for sample in samples))
    return payload[:start] + scaled.tobytes() + payload[start + len(scaled) * 2:]


def find_file(directory, candidates):
    if not os.path.isdir(directory):
        return None

    by_lower = {name.lower(): name for name in os.listdir(directory)}
    for candidate in candidates:
        found = by_lower.get(candidate.lower())
        if found:
            return os.path.join(directory, found)
    return None


def language_dirs(language):
    return {language.lower(), f"{language.lower()}2"}


def relocalize(name, source_dirs, target):
    parts = name.replace("/", "\\").split("\\")
    for index, part in enumerate(parts):
        if part.lower() in source_dirs:
            parts[index] = target
            return "\\".join(parts)
    return None


def archive_candidates(prefix, language, suffix):
    return [f"{prefix}{language}{suffix}.big", f"{prefix}{language}2{suffix}.big"]


def english_index(archive_paths):
    index = {}
    for path in archive_paths:
        if not path:
            continue
        for entry in big_entries(path):
            index.setdefault(entry.name.replace("/", "\\").lower(), entry)
    return index


def english_archives(directory, suffix):
    return [find_file(directory, [f"{prefix}English{suffix}.big"]) for _kind, prefix in ARCHIVE_KINDS]


def is_wanted(kind, entry_name):
    if kind != "textures":
        return True
    return TEXTURES_MARKER in entry_name.replace("/", "\\").lower()


def same_as(entry, reference, cache):
    if reference is None or reference.size != entry.size:
        return False
    return entry_digest(entry, cache) == entry_digest(reference, cache)


def base_name(entry_name):
    return entry_name.replace("/", "\\").split("\\")[-1].lower()


def collect_game(steam, language, directory, suffix, baseline, archive_name, cache, options):
    source_dirs = language_dirs(language)
    pack = GamePack(archive_name, [], {}, {})
    sound_names = set()

    for kind, prefix in ARCHIVE_KINDS:
        pack.counts[kind] = 0
        pack.totals[kind] = 0
        path = find_file(directory, archive_candidates(prefix, language, suffix))
        if not path:
            continue

        for entry in big_entries(path):
            if not is_wanted(kind, entry.name):
                continue

            target_name = relocalize(entry.name, source_dirs, language)
            english_name = relocalize(entry.name, source_dirs, "English")
            if target_name is None:
                print(f"    WARN {steam}: no language folder in {entry.name}", file=sys.stderr)
                continue

            pack.totals[kind] += 1
            if kind == "sounds":
                sound_names.add(base_name(entry.name))
                if options.drop_sounds:
                    continue
                if base_name(entry.name) in options.deferred_sound_names:
                    pack.deferred += 1
                    continue

            reference = baseline.get(english_name.lower())
            if same_as(entry, reference, cache):
                continue

            kept = Entry(target_name, entry.archive, entry.offset, entry.size)
            if kind == "sounds" and options.match_loudness and reference is not None:
                payload = louder_payload(entry, reference)
                if payload is not None:
                    kept = Entry(target_name, entry.archive, entry.offset, len(payload), payload)
                    pack.louder += 1

            pack.entries.append(kept)
            pack.counts[kind] += 1

    pack.sound_names = frozenset(sound_names)
    return pack


def source_movies_dir(steam):
    data = os.path.join(DEPOTS, steam, "Data")
    if not os.path.isdir(data):
        return None

    for name in os.listdir(data):
        movies = os.path.join(data, name, MOVIES_SUBDIR)
        if os.path.isdir(movies):
            return movies
    return None


def collect_movies(steam):
    source = source_movies_dir(steam)
    english = os.path.join(ENGLISH_DEPOT, "Data", "English", MOVIES_SUBDIR)
    if not source:
        return [], 0

    kept = []
    names = sorted(os.listdir(source))
    for name in names:
        path = os.path.join(source, name)
        reference = find_file(english, [name])
        if reference and os.path.getsize(reference) == os.path.getsize(path) \
                and file_digest(reference) == file_digest(path):
            continue
        kept.append(path)

    return kept, len(names)


def collect(steam, baselines, cache):
    spec = LOCALES[steam]
    language = spec["language"]
    depot = os.path.join(DEPOTS, steam)
    if not os.path.isdir(depot):
        raise SystemExit(f"missing depot: {depot} — run ./download_depots.sh {steam}")

    generals_source = spec.get("generalsSource")
    generals_dir = os.path.join(ROOT, generals_source) if generals_source else os.path.join(depot, GENERALS_SUBDIR)
    if not os.path.isdir(generals_dir):
        raise SystemExit(f"missing Generals source for {steam}: {generals_dir}")

    generals = collect_game(steam, language, generals_dir, "", baselines["generals"],
                            f"GOLocale{language}.big", cache,
                            GameOptions(match_loudness=spec.get("matchEnglishLoudness", False)))
    generals.source = generals_source or "depot"

    deferred = generals.sound_names if spec.get("zeroHourDefersBaseVoices") else frozenset()
    zero_hour = collect_game(steam, language, depot, "ZH", baselines["zero_hour"],
                             f"GOLocale{language}ZH.big", cache,
                             GameOptions(deferred_sound_names=deferred,
                                         drop_sounds=spec.get("zeroHourDropsOwnVoices", False)))
    movies, movies_total = collect_movies(steam)

    return LocalePack(steam, language, spec["packageVersion"], zero_hour, generals, movies, movies_total)


def load_baselines():
    if not os.path.isdir(ENGLISH_DEPOT):
        raise SystemExit(f"missing English depot: {ENGLISH_DEPOT} — run ./download_depots.sh english")

    zero_hour = english_archives(ENGLISH_DEPOT, "ZH")
    generals = english_archives(os.path.join(ENGLISH_DEPOT, GENERALS_SUBDIR), "")
    return {
        "zero_hour": english_index(zero_hour + generals),
        "generals": english_index(generals),
    }


def write_big(path, entries):
    ordered = sorted(entries, key=lambda entry: entry.name.lower())
    names = [entry.name.encode("latin-1") + b"\x00" for entry in ordered]
    index_size = sum(8 + len(name) for name in names)
    data_start = BIG_INDEX_START + index_size + len(BIG_TRAILER)
    total_size = data_start + sum(entry.size for entry in ordered)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as out:
        out.write(BIG_MAGIC)
        out.write(struct.pack("<I", total_size))
        out.write(struct.pack(">II", len(ordered), data_start))

        offset = data_start
        for entry, name in zip(ordered, names):
            out.write(struct.pack(">II", offset, entry.size))
            out.write(name)
            offset += entry.size
        out.write(BIG_TRAILER)

        for entry in ordered:
            copy_range(entry, out)


def copy_range(entry, out):
    if entry.payload is not None:
        out.write(entry.payload)
        return

    with open(entry.archive, "rb") as source:
        source.seek(entry.offset)
        remaining = entry.size
        while remaining:
            chunk = source.read(min(COPY_CHUNK, remaining))
            out.write(chunk)
            remaining -= len(chunk)


def link_or_copy(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def manifest(pack):
    return {
        "id": pack.language.lower(),
        "steamLanguage": pack.steam,
        "language": pack.language,
        "packageVersion": pack.package_version,
        "zeroHour": {"archive": pack.zero_hour.archive_name, **pack.zero_hour.counts,
                     "movies": len(pack.movies), "deferredToGenerals": pack.zero_hour.deferred},
        "generals": {"archive": pack.generals.archive_name, **pack.generals.counts,
                     "source": pack.generals.source, "loudnessRaised": pack.generals.louder},
    }


def build(pack):
    shutil.rmtree(pack.tree, ignore_errors=True)
    if pack.is_empty:
        return

    if pack.zero_hour.entries:
        write_big(os.path.join(pack.tree, "Assets", pack.zero_hour.archive_name), pack.zero_hour.entries)
    if pack.generals.entries:
        write_big(os.path.join(pack.tree, "AssetsGenerals", pack.generals.archive_name), pack.generals.entries)
    for movie in pack.movies:
        link_or_copy(movie, os.path.join(pack.tree, "Assets", "Data", pack.language, MOVIES_SUBDIR,
                                         os.path.basename(movie)))

    with open(os.path.join(pack.tree, "locale.json"), "w") as handle:
        json.dump(manifest(pack), handle, indent=2)
        handle.write("\n")


def verify(pack):
    for folder, game in (("Assets", pack.zero_hour), ("AssetsGenerals", pack.generals)):
        if not game.entries:
            continue

        path = os.path.join(pack.tree, folder, game.archive_name)
        written = {entry.name: entry.size for entry in big_entries(path)}
        expected = {entry.name: entry.size for entry in game.entries}
        if written != expected:
            raise SystemExit(f"verify failed: {path}")


def megabytes(size):
    return f"{size / 1024 ** 2:.0f}"


def counts_cell(game):
    return " ".join(f"{game.counts[kind]}/{game.totals[kind]}" for kind, _prefix in ARCHIVE_KINDS)


def report(packs):
    print()
    print("| Язык | ZH звуки/речь/текстуры | Generals звуки/речь/текстуры | Ролики | Пакет, MB |")
    print("|---|---|---|---|---|")
    for pack in packs:
        size = pack.zero_hour.size + pack.generals.size + pack.movies_size
        verdict = "нет пакета" if pack.is_empty else megabytes(size)
        print(f"| {pack.steam} → {pack.language} | {counts_cell(pack.zero_hour)} | "
              f"{counts_cell(pack.generals)} | {len(pack.movies)}/{pack.movies_total} | {verdict} |")

    for pack in packs:
        if pack.generals.source != "depot":
            print(f"{pack.steam}: Generals из {pack.generals.source}, "
                  f"громкость поднята у {pack.generals.louder} звуков")
        if pack.zero_hour.deferred:
            print(f"{pack.steam}: ZH отдаёт базе {pack.zero_hour.deferred} реплик юнитов")


def tree_dir(steam):
    return os.path.join(ROOT, f"GO_Mac_Locale_{LOCALES[steam]['language']}")


def tree_files(directory):
    return [os.path.join(current, name) for current, _dirs, names in os.walk(directory) for name in names]


def size_mb(paths):
    return round(sum(os.path.getsize(path) for path in paths) / 1024 ** 2)


def catalog_markers(tree, built):
    archives = [("Assets", built["zeroHour"]["archive"]), ("AssetsGenerals", built["generals"]["archive"])]
    return [f"{folder}/{name}" for folder, name in archives if os.path.isfile(os.path.join(tree, folder, name))]


def catalog_entry(steam):
    tree = tree_dir(steam)
    zip_path = f"{tree}.zip"
    if not os.path.isfile(zip_path):
        raise SystemExit(f"no release zip for {os.path.basename(tree)}: run ./pack_upload.sh --no-upload first")

    with open(os.path.join(tree, "locale.json")) as handle:
        built = json.load(handle)

    zero_hour = built["zeroHour"]
    generals = built["generals"]
    return {
        "id": built["id"],
        "language": built["language"],
        "packageVersion": built["packageVersion"],
        "urls": [f"{RELEASE_BASE}/{os.path.basename(zip_path)}"],
        "downloadSizeMB": size_mb([zip_path]),
        "diskSizeMB": size_mb(path for path in tree_files(tree) if not path.endswith("locale.json")),
        "markers": catalog_markers(tree, built),
        "voices": {
            "zeroHour": zero_hour["sounds"] + zero_hour["speech"] > 0,
            "generals": generals["sounds"] + generals["speech"] > 0,
        },
        "movies": zero_hour["movies"],
        "textures": zero_hour["textures"] + generals["textures"],
    }


def write_catalog():
    if not os.path.isdir(os.path.dirname(CATALOG)):
        raise SystemExit(f"site repository not found: {os.path.dirname(CATALOG)}")

    built = [steam for steam in LOCALES if os.path.isdir(tree_dir(steam))]
    catalog = {"version": CATALOG_VERSION, "locales": [catalog_entry(steam) for steam in built]}
    with open(CATALOG, "w") as handle:
        json.dump(catalog, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"==> {os.path.relpath(CATALOG, ROOT)}: {len(built)} locales")


def selected(names):
    if not names:
        return list(LOCALES)

    unknown = [name for name in names if name not in LOCALES]
    if unknown:
        raise SystemExit(f"unknown language: {' '.join(unknown)} (known: {' '.join(LOCALES)})")
    return names


def main():
    parser = argparse.ArgumentParser(description="Assemble locale packs from Steam depots")
    parser.add_argument("languages", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--catalog", action="store_true")
    args = parser.parse_args()

    if args.catalog:
        write_catalog()
        return

    cache = {}
    baselines = load_baselines()
    packs = []
    for steam in selected(args.languages):
        print(f"==> {steam}")
        pack = collect(steam, baselines, cache)
        packs.append(pack)
        if args.dry_run:
            continue
        build(pack)
        verify(pack)

    report(packs)


if __name__ == "__main__":
    main()
