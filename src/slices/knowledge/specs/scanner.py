"""Scan Dizi repo (src + legacy Dizi API) and generate unified architecture specs."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from core.config import get_settings
from slices.knowledge.specs.format import ArchitectureSpec, build_spec

SKIP_DIRS = {
    "bin",
    "obj",
    ".git",
    ".vs",
    "node_modules",
    "Properties",
}
STRUCTURE_NEW = "new-structure"
STRUCTURE_LEGACY = "legacy-api"

PATTERN_RULES_NEW = [
    ("command", "*Command.cs", "MediatR command DTO implementing IRequest<CommandResult<T>>"),
    ("command-handler", "*CommandHandler.cs", "Handler in AppServices implementing IRequestHandler"),
    ("command-validator", "*CommandValidator.cs", "FluentValidation validator for command"),
    ("query", "*Query.cs", "MediatR query implementing IRequest<QueryResult<T>>"),
    ("query-handler", "*QueryHandler.cs", "Query handler in AppServices"),
    ("entity", "*.cs", "Domain entity / aggregate under Domain/{BC}/Entities"),
    ("repository-interface", "I*Repository.cs", "Repository abstraction in Shared/{BC}/Commands|Queries"),
    ("endpoint-controller", "*Controller.cs", "API controller in Endpoints/{App}.Api"),
    ("domain-service", "*Service.cs", "Domain service in AppCore/DomainServices"),
]

LEGACY_SUBFOLDERS = [
    "Abstractions",
    "Services",
    "Dtos",
    "Entities",
    "Enums",
    "Validators",
    "Controllers",
    "Scripts",
    "Consumers",
    "Producers",
    "Events",
    "Extensions",
]


def _should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _walk_cs_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".cs"):
                files.append(Path(dirpath) / name)
    return files


def _match_pattern(filename: str, pattern: str) -> bool:
    if pattern.startswith("*") and pattern.endswith(".cs"):
        return filename.endswith(pattern[1:])
    return filename == pattern


def _count_patterns(files: list[Path], root: Path) -> dict[str, list[str]]:
    counts: dict[str, list[str]] = defaultdict(list)
    for f in files:
        name = f.name
        rel = _rel(f, root)
        for key, glob, _desc in PATTERN_RULES_NEW:
            if _match_pattern(name, glob) or (glob == "*.cs" and "/Entities/" in rel.replace("\\", "/")):
                if glob == "*.cs" and "/Entities/" not in rel.replace("\\", "/"):
                    continue
                counts[key].append(rel)
    return counts


def _list_dirs(path: Path, depth: int = 1) -> list[str]:
    if not path.exists():
        return []
    items = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and child.name not in SKIP_DIRS:
            items.append(child.name)
            if depth > 1:
                for sub in sorted(child.iterdir()):
                    if sub.is_dir() and sub.name not in SKIP_DIRS:
                        items.append(f"{child.name}/{sub.name}")
    return items


def _bounded_contexts(shared_root: Path) -> list[str]:
    if not shared_root.exists():
        return []
    return sorted(
        d.name
        for d in shared_root.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS and d.name != "Base"
    )


def _feature_modules(features_root: Path) -> list[str]:
    if not features_root.exists():
        return []
    return sorted(
        d.name
        for d in features_root.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS
    )


def _legacy_feature_layout(feature_path: Path) -> dict[str, int]:
    layout: dict[str, int] = defaultdict(int)
    for f in _walk_cs_files(feature_path):
        for part in f.parts:
            if part in LEGACY_SUBFOLDERS:
                layout[part] += 1
    return dict(layout)


def _endpoint_apps(endpoints_root: Path) -> list[str]:
    if not endpoints_root.exists():
        return []
    return sorted(
        d.name
        for d in endpoints_root.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS and d.name != "Base"
    )


def _body_section(title: str, lines: list[str]) -> str:
    return f"## {title}\n\n" + "\n".join(lines) + "\n"


def scan_dizi_repository(
    repo_path: Path | None = None,
    branch: str | None = None,
) -> list[ArchitectureSpec]:
    settings = get_settings()
    repo = Path(repo_path or settings.dizi_repo_path)
    branch_name = branch or settings.dizi_spec_branch
    src_root = repo / settings.dizi_src_relative
    legacy_root = repo / settings.dizi_legacy_api_relative

    specs: list[ArchitectureSpec] = []

    # --- New structure overview ---
    src_files = _walk_cs_files(src_root)
    bc_list = _bounded_contexts(src_root / "AppCore" / "Shared")
    endpoint_apps = _endpoint_apps(src_root / "Endpoints")
    infra_areas = _list_dirs(src_root / "Infra")

    overview_body = (
        _body_section(
            "Purpose",
            [
                "Dizi **new structure** under `src/` on branch "
                f"`{branch_name}`. Clean architecture with CQRS, MediatR, FluentValidation, "
                "and multi-host endpoints (ChefApp, VendorApp, BackOfficeApp).",
            ],
        )
        + _body_section(
            "Top-Level Layers",
            [
                "- **AppCore** — Domain, Shared (contracts), AppServices (handlers), DomainServices",
                "- **Endpoints** — Host-specific API projects + Base + Observability",
                "- **Infra** — Persistence (MySql Commands/Queries), Auth, Integrations (MM, OMS, Iris, ...)",
            ],
        )
        + _body_section(
            "Bounded Contexts (AppCore/Shared)",
            [f"- {bc}" for bc in bc_list] or ["- (none detected)"],
        )
        + _body_section(
            "Endpoint Hosts",
            [f"- {app}" for app in endpoint_apps] or ["- (none detected)"],
        )
        + _body_section(
            "Infra Areas",
            [f"- {area}" for area in infra_areas] or ["- (none detected)"],
        )
        + _body_section(
            "Statistics",
            [
                f"- C# files under src/: **{len(src_files)}**",
                f"- Repository root: `{repo}`",
            ],
        )
        + _body_section(
            "Rules for Agents",
            [
                "1. Place commands/queries in `AppCore/Shared/{BC}/Commands|Queries`",
                "2. Handlers + validators in `AppCore/AppServices/{BC}/...`",
                "3. Domain logic in `AppCore/Domain/{BC}` aggregates/entities/rules",
                "4. Persistence in `Infra/Persistence/MySql.Commands|Queries/{BC}`",
                "5. Expose via thin controllers in `Endpoints/{Host}.Api/{BC}` using BaseApiController + MediatR",
                "6. Tag all generated knowledge with `new-structure`",
            ],
        )
    )

    specs.append(
        build_spec(
            spec_id="dizi.new-structure.overview",
            title="Dizi New Structure — Architecture Overview",
            structure_tag=STRUCTURE_NEW,
            source_kind="architecture",
            source_path=settings.dizi_src_relative,
            branch=branch_name,
            layers=["AppCore", "Endpoints", "Infra"],
            extra_tags=["overview", "architecture"],
            body=overview_body,
        )
    )

    # --- Layer specs ---
    layer_map = {
        "appcore": (src_root / "AppCore", ["Domain", "Shared", "AppServices", "DomainServices"]),
        "endpoints": (src_root / "Endpoints", endpoint_apps),
        "infra": (src_root / "Infra", infra_areas),
    }
    for layer_key, (layer_path, children) in layer_map.items():
        layer_files = _walk_cs_files(layer_path)
        child_lines = [f"- **{c}**" for c in children] if isinstance(children[0], str) else []
        if layer_key == "appcore":
            child_lines = [f"- **{c}**" for c in children]
        body = (
            _body_section("Purpose", [f"Layer `{layer_key}` responsibilities and layout."])
            + _body_section("Sub-areas", child_lines or ["- (none)"])
            + _body_section("File Count", [f"- `{len(layer_files)}` C# files"])
            + _body_section(
                "Rules for Agents",
                [
                    f"- Stay within `src/{layer_key.title() if layer_key != 'appcore' else 'AppCore'}/` boundaries",
                    "- Do not reference Endpoints from Domain",
                    "- Shared project holds contracts only; handlers live in AppServices",
                ],
            )
        )
        specs.append(
            build_spec(
                spec_id=f"dizi.new-structure.layer.{layer_key}",
                title=f"Dizi New Structure — {layer_key.upper()} Layer",
                structure_tag=STRUCTURE_NEW,
                source_kind="layer",
                source_path=f"{settings.dizi_src_relative}/{layer_path.name}",
                branch=branch_name,
                layers=[layer_key],
                extra_tags=["layer"],
                body=body,
            )
        )

    # --- Pattern spec (aggregate) ---
    patterns = _count_patterns(src_files, src_root)
    pattern_lines = []
    for key, _glob, desc in PATTERN_RULES_NEW:
        samples = patterns.get(key, [])[:5]
        pattern_lines.append(f"### {key}")
        pattern_lines.append(f"- **Description:** {desc}")
        pattern_lines.append(f"- **Count:** {len(patterns.get(key, []))}")
        if samples:
            pattern_lines.append("- **Examples:**")
            pattern_lines.extend(f"  - `{s}`" for s in samples)
        pattern_lines.append("")

    pattern_body = (
        _body_section("Purpose", ["Standard CQRS/MediatR patterns for new `src/` structure."])
        + "## Patterns\n\n"
        + "\n".join(pattern_lines)
        + _body_section(
            "Command Handler Template",
            [
                "```csharp",
                "public class XCommandHandler(IRepo repo)",
                "    : IRequestHandler<XCommand, CommandResult<bool>>",
                "{",
                "    public async Task<CommandResult<bool>> Handle(XCommand request, CancellationToken ct)",
                "    {",
                "        // domain factory + repository + CommitAsync",
                "        return CommandResult<bool>.Success(true);",
                "    }",
                "}",
                "```",
            ],
        )
        + _body_section(
            "Endpoint Template",
            [
                "```csharp",
                "[Route(\"chef-app/api/v{version:apiVersion}/...\")]",
                "public class XController(IMediator m, IServiceProvider sp) : BaseApiController(m, sp)",
                "{",
                "    [HttpPost(\"add\")]",
                "    public async Task<IActionResult> Add([FromBody] XCommand cmd)",
                "        => await SendCommandAsync(cmd);",
                "}",
                "```",
            ],
        )
    )
    specs.append(
        build_spec(
            spec_id="dizi.new-structure.patterns.cqrs",
            title="Dizi New Structure — CQRS & Endpoint Patterns",
            structure_tag=STRUCTURE_NEW,
            source_kind="pattern",
            source_path=settings.dizi_src_relative,
            branch=branch_name,
            extra_tags=["pattern", "cqrs", "mediatr"],
            body=pattern_body,
        )
    )

    # --- Bounded context specs ---
    for bc in bc_list:
        bc_files = [f for f in src_files if f"/{bc}/" in _rel(f, src_root).replace("\\", "/")]
        bc_patterns = _count_patterns(bc_files, src_root)
        cmd_count = len(bc_patterns.get("command", [])) + len(bc_patterns.get("command-handler", []))
        query_count = len(bc_patterns.get("query", [])) + len(bc_patterns.get("query-handler", []))
        body = (
            _body_section("Purpose", [f"Bounded context **{bc}** in new structure."])
            + _body_section(
                "Folder Map",
                [
                    f"- `AppCore/Domain/{bc}/` — entities, rules, enums",
                    f"- `AppCore/Shared/{bc}/` — commands, queries, repository interfaces",
                    f"- `AppCore/AppServices/{bc}/` — handlers, validators",
                    f"- `Infra/Persistence/MySql.*/{bc}/` — persistence",
                    f"- `Endpoints/*/Api/{bc}/` — HTTP controllers",
                ],
            )
            + _body_section(
                "Metrics",
                [
                    f"- Files: {len(bc_files)}",
                    f"- Commands (approx): {cmd_count}",
                    f"- Queries (approx): {query_count}",
                ],
            )
            + _body_section(
                "Rules for Agents",
                [
                    f"- New features for {bc} must follow Shared → AppServices → Infra → Endpoints flow",
                    "- Keep aggregate rules in Domain; no HTTP types in AppCore",
                ],
            )
        )
        specs.append(
            build_spec(
                spec_id=f"dizi.new-structure.bc.{bc.lower()}",
                title=f"Dizi BC — {bc} (New Structure)",
                structure_tag=STRUCTURE_NEW,
                source_kind="bounded-context",
                source_path=f"{settings.dizi_src_relative}/AppCore/Shared/{bc}",
                branch=branch_name,
                bounded_context=bc,
                layers=["AppCore", "Infra", "Endpoints"],
                extra_tags=["bounded-context", bc.lower()],
                body=body,
            )
        )

    # --- Legacy API overview ---
    legacy_files = _walk_cs_files(legacy_root)
    features = _feature_modules(legacy_root / "Features")
    legacy_body = (
        _body_section(
            "Purpose",
            [
                "Legacy **Dizi API** monolith under `Dizi/` — feature folders, gateway services, "
                "direct controllers. Preserved for reference and gradual migration to `src/`.",
            ],
        )
        + _body_section(
            "Layout",
            [
                "- `Dizi/Features/{Feature}/` — vertical feature modules",
                "- Common subfolders: Abstractions, Services, Dtos, Entities, Controllers, Validators",
                "- `Dizi/Features/Integrations/*` — MM, OMS, Yggdrasil gateway controllers",
                "- `Dizi/Consumers/` — messaging consumers",
            ],
        )
        + _body_section(
            "Feature Modules",
            [f"- {feat}" for feat in features] or ["- (none)"],
        )
        + _body_section(
            "Statistics",
            [f"- C# files under Dizi/: **{len(legacy_files)}**"],
        )
        + _body_section(
            "Rules for Agents",
            [
                "1. Legacy code lives under `Dizi/Features/` — do not mix with `src/` patterns",
                "2. Controllers often delegate to *GatewayService or *Service classes",
                "3. When migrating, map Feature → Bounded Context in new structure",
                "4. Tag knowledge with `legacy-api`",
            ],
        )
    )
    specs.append(
        build_spec(
            spec_id="dizi.legacy-api.overview",
            title="Dizi Legacy API — Architecture Overview",
            structure_tag=STRUCTURE_LEGACY,
            source_kind="architecture",
            source_path=settings.dizi_legacy_api_relative,
            branch=branch_name,
            extra_tags=["overview", "legacy"],
            body=legacy_body,
        )
    )

    legacy_pattern_body = _body_section(
        "Legacy Feature Folder Pattern",
        [
            "```",
            "Dizi/Features/{FeatureName}/",
            "  Abstractions/     # interfaces",
            "  Services/         # business / gateway services",
            "  Dtos/             # request/response models",
            "  Entities/         # EF / domain entities",
            "  Validators/       # FluentValidation",
            "  Controllers/      # optional local controllers",
            "  Scripts/          # SQL migrations/scripts",
            "```",
        ],
    ) + _body_section(
        "Controller Pattern",
        [
            "- `[ApiController]` + `[Route(\"api/...\")]`",
            "- Inject `*GatewayService` or domain `*Service`",
            "- Return `StatusCode(response.StatusCode, response)` from gateway",
        ],
    )
    specs.append(
        build_spec(
            spec_id="dizi.legacy-api.patterns.feature-module",
            title="Dizi Legacy API — Feature Module Pattern",
            structure_tag=STRUCTURE_LEGACY,
            source_kind="pattern",
            source_path=settings.dizi_legacy_api_relative,
            branch=branch_name,
            extra_tags=["pattern", "legacy"],
            body=legacy_pattern_body,
        )
    )

    for feat in features:
        feat_path = legacy_root / "Features" / feat
        layout = _legacy_feature_layout(feat_path)
        layout_lines = [f"- **{k}:** {v} files" for k, v in sorted(layout.items())]
        feat_file_count = len(_walk_cs_files(feat_path))
        body = (
            _body_section("Purpose", [f"Legacy feature module **{feat}**."])
            + _body_section("Path", [f"`Dizi/Features/{feat}/`"])
            + _body_section("Subfolder Usage", layout_lines or ["- (no standard subfolders detected)"])
            + _body_section("File Count", [f"- {feat_file_count} C# files"])
        )
        specs.append(
            build_spec(
                spec_id=f"dizi.legacy-api.feature.{feat.lower()}",
                title=f"Dizi Legacy Feature — {feat}",
                structure_tag=STRUCTURE_LEGACY,
                source_kind="feature",
                source_path=f"{settings.dizi_legacy_api_relative}/Features/{feat}",
                branch=branch_name,
                extra_tags=["feature", feat.lower()],
                body=body,
            )
        )

    return specs
