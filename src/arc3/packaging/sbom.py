"""Deterministic SPDX inventory with version-keyed license evidence."""

from __future__ import annotations

import tomllib
import zipfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from arc3.packaging.models import PackagingError
from arc3.packaging.requirements import LockedWheel
from arc3.packaging.util import sha256_bytes, sha256_file
from arc3.types import JSONValue

AGENTS_COMMIT = "4743e7d0aaae0ded0d98a89a7e282e63564cd58b"


@dataclass(frozen=True, slots=True)
class _LicenseEvidence:
    expression: str
    source: str
    identity: str
    additional: tuple[tuple[str, str], ...] = ()


# Evidence is keyed by the exact locked distribution version. Identities name
# the license/notice file when available, otherwise the pinned artifact or Git blob.
_LICENSE_EVIDENCE: dict[str, _LicenseEvidence] = {
    "annotated-types==0.8.0": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "fe1049884b1a0d9342901e88e07f32925d24b3121d9972b6a6805fb9824b095d",
    ),
    "arc-agi==0.9.9": _LicenseEvidence(
        "MIT", "Git LICENSE blob SHA-1", "80216ed3bbd1749bf73b6ab13188db27178b4578"
    ),
    "arcengine==0.9.3": _LicenseEvidence(
        "MIT",
        "locked sdist SHA-256 with METADATA License",
        "76441c15fde092a071ca95edce5e643385ab270304f59c1172b460048fffcdfe",
    ),
    "blinker==1.9.0": _LicenseEvidence(
        "MIT",
        "wheel:LICENSE.txt",
        "9eb73a1f38597a4aa17025d2ae1be3839624c795e985d4f0e9769ce29faca467",
    ),
    "certifi==2026.7.22": _LicenseEvidence(
        "MPL-2.0",
        "wheel:licenses/LICENSE",
        "e93716da6b9c0d5a4a1df60fe695b370f0695603d21f6f83f053e42cfc10caf7",
    ),
    "charset-normalizer==3.5.1": _LicenseEvidence(
        "MIT",
        "wheel:charset_normalizer-3.5.1.dist-info/licenses/LICENSE",
        "6d0d41bfe170ac6c7dc248c9a63e254d0fb45a60d50a8257d0af92c6e249b887",
    ),
    "click==8.4.2": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE.txt",
        "9a8ad106a394e853bfe21f42f4e72d592819a22805d991b5f3275029292b658d",
    ),
    "contourpy==1.3.3": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:contourpy-1.3.3.dist-info/LICENSE",
        "34170979fc64f4f5e6dfa66ef27dec314ffffc5852000c60f4836ec1dfbf156e",
    ),
    "cycler==0.12.1": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:LICENSE",
        "f1218143d766da3fea66f13396b7f15df46a83303f29bf96ba6e98eb4d42f408",
    ),
    "flask==3.1.3": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE.txt",
        "489a8e1108509ed98a37bb983e11e0f7e1d31f0bd8f99a79c8448e7ff37d07ea",
    ),
    "fonttools==4.63.0": _LicenseEvidence(
        "MIT",
        "wheel:fonttools-4.63.0.dist-info/licenses/LICENSE",
        "6787208f83f659ccbc2223b2fde952ffa6f7e8aca62f1a8a2bf5bc51bb1b2383",
        (
            (
                "wheel:fonttools-4.63.0.dist-info/licenses/LICENSE.external",
                "94a83aaee0729a0f302d34acc4acecbd9d58366f262429075fe557e4a54b2e69",
            ),
        ),
    ),
    "idna==3.19": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE.md",
        "1a9a4f0e3d479a27240ddd59a9137a66ab4a0f9dfdc8ca6188cc0bfd85187f04",
    ),
    "itsdangerous==2.2.0": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:LICENSE.txt",
        "63af09891b6be8ad1a4252ed43af0f4efba7fc948e228367bed7f3c5ae0b09d7",
    ),
    "jinja2==3.1.6": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE.txt",
        "3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b",
    ),
    "kiwisolver==1.5.0": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:kiwisolver-1.5.0.dist-info/licenses/LICENSE",
        "529c40e5f67f2f88904657a9f7879ae2f8dc76bc9bfef9cb10d988b48804ed61",
    ),
    "markupsafe==3.0.3": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:markupsafe-3.0.3.dist-info/licenses/LICENSE.txt",
        "489a8e1108509ed98a37bb983e11e0f7e1d31f0bd8f99a79c8448e7ff37d07ea",
    ),
    "matplotlib==3.11.1": _LicenseEvidence(
        "LicenseRef-Matplotlib-3.11.1-Composite",
        "wheel:LICENSE",
        "822e8e528147569a41975592aee19c11992ab667ba50451cd929031d5fc74491",
    ),
    "numpy==2.5.2": _LicenseEvidence(
        "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
        "wheel:numpy-2.5.2.dist-info/licenses/LICENSE.txt",
        "4860083caa0de2ac3292ca98bd074bd8f45d8b32624e37b1e70a240bff61e488",
    ),
    "packaging==26.3": _LicenseEvidence(
        "Apache-2.0 OR BSD-2-Clause",
        "wheel:licenses/LICENSE",
        "cad1ef5bd340d73e074ba614d26f7deaca5c7940c3d8c34852e65c4909686c48",
    ),
    "pillow==12.3.0": _LicenseEvidence(
        "MIT-CMU",
        "wheel:pillow-12.3.0.dist-info/licenses/LICENSE",
        "dda12a98c1979cf3d94df1cff45d27a4cb3f04a60c76f76902ac54cac03ec0ce",
    ),
    "pydantic==2.13.4": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "a9e186f3ca16b5eef84318e7a701721351a00cb7b8ae3a4394b67b49e3529ef3",
    ),
    "pydantic-core==2.46.4": _LicenseEvidence(
        "MIT",
        "wheel:pydantic_core-2.46.4.dist-info/licenses/LICENSE",
        "2afdd30d54b4d62b6f488a6bcc1546e84ec5061f13f4209c03d012348783795a",
    ),
    "pyparsing==3.3.2": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "a5425f9dc14ac74d4c5f0b679e941f2442e32cca7452a4418d5b1a49893ebe4e",
    ),
    "python-dateutil==2.9.0.post0": _LicenseEvidence(
        "Apache-2.0 OR BSD-3-Clause",
        "wheel:LICENSE",
        "ba00f51a0d92823b5a1cde27d8b5b9d2321e67ed8da9bc163eff96d5e17e577e",
    ),
    "python-dotenv==1.2.3": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE",
        "80619b7049f08c81683ad0e01f08f257a840652dd71ee83146d36658c7d2c2b9",
    ),
    "requests==2.34.2": _LicenseEvidence(
        "Apache-2.0",
        "wheel:licenses/LICENSE",
        "09e8a9bcec8067104652c168685ab0931e7868f9c8284b66f5ae6edae5f1130b",
    ),
    "six==1.17.0": _LicenseEvidence(
        "MIT", "wheel:LICENSE", "4375ba20e2b9c6c4e7cad2940a628fd90e95cc3d50ee92aae755715d8ba1fbd0"
    ),
    "typing-extensions==4.16.0": _LicenseEvidence(
        "PSF-2.0",
        "wheel:licenses/LICENSE",
        "3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf",
    ),
    "typing-inspection==0.4.4": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "804b59b25f2c31bd278f9202a19ae49a3945aa2664387e2d0a128c7cacc61ec3",
    ),
    "urllib3==2.7.0": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE.txt",
        "130e3a64d5fdd5d096a752694634a7d9df284469de86e5732100268041e3d686",
    ),
    "werkzeug==3.1.8": _LicenseEvidence(
        "BSD-3-Clause",
        "wheel:licenses/LICENSE.txt",
        "3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b",
    ),
    "pyarrow==21.0.0": _LicenseEvidence(
        "Apache-2.0",
        "wheel:pyarrow-21.0.0.dist-info/LICENSE.txt",
        "82f5f9b0e6592da7f79022fc930add132a76c56727d29813f94058157a2b2d11",
        (
            (
                "wheel:pyarrow-21.0.0.dist-info/NOTICE.txt",
                "c946470d6b024c77feebdfb686bf92a828402c0ffc27c769bca7d8bef08e1db7",
            ),
        ),
    ),
    "hatchling==1.32.0": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE.txt",
        "7f143a8127ad4873862d70854b5bd2abd0085aa73e64fd2b08704a3b9f5c07fc",
    ),
    "pathspec==1.1.1": _LicenseEvidence(
        "MPL-2.0",
        "wheel:licenses/LICENSE",
        "fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85",
    ),
    "pluggy==1.6.0": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606",
    ),
    "tomlkit==0.15.1": _LicenseEvidence(
        "MIT",
        "wheel:licenses/LICENSE",
        "f2f9b460ba719da6626add264d3782f275a4ff7aab677beda08b330911e23adb",
    ),
    "trove-classifiers==2026.6.1.19": _LicenseEvidence(
        "Apache-2.0",
        "wheel:licenses/LICENSE",
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    ),
}


def _spdx_id(name: str) -> str:
    normalized = "".join(character if character.isalnum() else "-" for character in name)
    return f"SPDXRef-Package-{normalized}"


def _license_for(name: str, version: str) -> _LicenseEvidence:
    key = f"{name}=={version}"
    try:
        return _LICENSE_EVIDENCE[key]
    except KeyError as error:
        raise PackagingError(f"no version-keyed license evidence for package {key}") from error


def verify_wheelhouse_license_evidence(
    wheels: tuple[LockedWheel, ...], wheelhouse: Path
) -> dict[str, JSONValue]:
    """Verify selected wheel bytes and embedded license evidence without network access."""

    if not wheelhouse.is_dir():
        raise PackagingError(f"license wheelhouse does not exist: {wheelhouse}")
    verified: list[JSONValue] = []
    for wheel in sorted(wheels, key=lambda item: item.name):
        archive_path = wheelhouse / wheel.filename
        if not archive_path.is_file():
            raise PackagingError(f"license wheelhouse is missing {wheel.filename}")
        if sha256_file(archive_path) != wheel.sha256:
            raise PackagingError(f"selected wheel hash mismatch for {wheel.name}=={wheel.version}")
        evidence = _license_for(wheel.name, wheel.version)
        declarations = ((evidence.source, evidence.identity), *evidence.additional)
        if any(not source.startswith("wheel:") for source, _ in declarations):
            raise PackagingError(
                f"license evidence is not embedded-wheel evidence for {wheel.name}=={wheel.version}"
            )
        verified_files: list[JSONValue] = []
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                for source, expected_sha256 in declarations:
                    expected_member = source.removeprefix("wheel:")
                    matches = [
                        name
                        for name in names
                        if name == expected_member or name.endswith("/" + expected_member)
                    ]
                    if len(matches) != 1:
                        raise PackagingError(
                            f"selected wheel has no unique {expected_member} for "
                            f"{wheel.name}=={wheel.version}"
                        )
                    content = archive.read(matches[0])
                    if sha256_bytes(content) != f"sha256:{expected_sha256}":
                        raise PackagingError(
                            f"selected wheel license evidence mismatch for "
                            f"{wheel.name}=={wheel.version}"
                        )
                    verified_files.append(
                        {
                            "path": matches[0],
                            "sha256": f"sha256:{expected_sha256}",
                            "size_bytes": len(content),
                        }
                    )
        except zipfile.BadZipFile as error:
            raise PackagingError(f"selected wheel is not a valid ZIP: {wheel.filename}") from error
        verified.append(
            {
                "license_files": verified_files,
                "name": wheel.name,
                "version": wheel.version,
                "wheel_filename": wheel.filename,
                "wheel_sha256": wheel.sha256,
            }
        )
    return {
        "packages": verified,
        "schema": "arc3.wheelhouse-license-verification.v0.1",
        "status": "PASS",
    }


def _runtime_package(wheel: LockedWheel) -> dict[str, JSONValue]:
    evidence = _license_for(wheel.name, wheel.version)
    evidence_comment = "; ".join(
        f"{source} {identity}"
        for source, identity in (
            (evidence.source, evidence.identity),
            *evidence.additional,
        )
    )
    return {
        "SPDXID": _spdx_id(wheel.name),
        "checksums": [
            {"algorithm": "SHA256", "checksumValue": wheel.sha256.removeprefix("sha256:")}
        ],
        "downloadLocation": wheel.url,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceLocator": f"pkg:pypi/{wheel.name}@{wheel.version}",
                "referenceType": "purl",
            }
        ],
        "filesAnalyzed": False,
        "licenseComments": f"version-keyed evidence {evidence_comment}",
        "licenseConcluded": evidence.expression,
        "licenseDeclared": evidence.expression,
        "name": wheel.name,
        "primaryPackagePurpose": "LIBRARY",
        "supplier": "NOASSERTION",
        "versionInfo": wheel.version,
    }


def _locked_pyarrow_linux_wheel(lock_path: Path) -> LockedWheel:
    parsed = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise PackagingError("uv.lock has no package array")
    for package in packages:
        if not isinstance(package, dict) or package.get("name") != "pyarrow":
            continue
        version = package.get("version")
        raw_wheels = package.get("wheels")
        if not isinstance(version, str) or not isinstance(raw_wheels, list):
            break
        matches = [
            wheel
            for wheel in raw_wheels
            if isinstance(wheel, dict)
            and isinstance(wheel.get("url"), str)
            and "-cp312-cp312-manylinux_2_28_x86_64.whl" in cast(str, wheel["url"])
            and isinstance(wheel.get("hash"), str)
        ]
        if len(matches) != 1:
            break
        url = cast(str, matches[0]["url"])
        digest = cast(str, matches[0]["hash"])
        filename = Path(urlparse(url).path).name
        if not digest.startswith("sha256:"):
            break
        return LockedWheel("pyarrow", version, filename, digest, url)
    raise PackagingError("uv.lock has no unique CPython 3.12 Linux x86_64 PyArrow wheel")


def _locked_pure_wheel(lock_path: Path, name: str) -> tuple[str, str, str]:
    parsed = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise PackagingError("uv.lock has no package array")
    for package in packages:
        if not isinstance(package, dict) or package.get("name") != name:
            continue
        version = package.get("version")
        wheels = package.get("wheels")
        if not isinstance(version, str) or not isinstance(wheels, list):
            break
        matches = [
            wheel
            for wheel in wheels
            if isinstance(wheel, dict)
            and isinstance(wheel.get("url"), str)
            and cast(str, wheel["url"]).endswith("-none-any.whl")
            and isinstance(wheel.get("hash"), str)
        ]
        if len(matches) != 1:
            break
        url = cast(str, matches[0]["url"])
        digest = cast(str, matches[0]["hash"])
        if not digest.startswith("sha256:"):
            break
        return version, url, digest
    raise PackagingError(f"uv.lock has no unique pure wheel for build-only package {name!r}")


def _build_only_package(lock_path: Path, name: str) -> dict[str, JSONValue]:
    version, url, digest = _locked_pure_wheel(lock_path, name)
    evidence = _license_for(name, version)
    return {
        "SPDXID": _spdx_id(f"{name}-build-only"),
        "checksums": [{"algorithm": "SHA256", "checksumValue": digest.removeprefix("sha256:")}],
        "downloadLocation": url,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceLocator": f"pkg:pypi/{name}@{version}",
                "referenceType": "purl",
            }
        ],
        "filesAnalyzed": False,
        "licenseComments": f"build-only version-keyed evidence {evidence.source} {evidence.identity}",
        "licenseConcluded": evidence.expression,
        "licenseDeclared": evidence.expression,
        "name": name,
        "primaryPackagePurpose": "LIBRARY",
        "supplier": "NOASSERTION",
        "versionInfo": version,
    }


def _installed_license_text(name: str, version: str, *, filename: str, expected_sha256: str) -> str:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError as error:
        raise PackagingError(
            f"cannot extract {name} license: distribution is not installed"
        ) from error
    if distribution.version != version or distribution.files is None:
        raise PackagingError(f"cannot extract license for exact distribution {name}=={version}")
    matches = [item for item in distribution.files if item.name == filename]
    if len(matches) != 1:
        raise PackagingError(f"cannot uniquely locate {filename} for {name}=={version}")
    path = Path(str(distribution.locate_file(matches[0])))
    content = path.read_bytes()
    if sha256_bytes(content) != f"sha256:{expected_sha256}":
        raise PackagingError(f"installed {name} license differs from version-keyed evidence")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PackagingError(f"installed {name} license is not UTF-8") from error


def build_spdx_sbom(
    lock_path: Path,
    *,
    runtime_wheels: tuple[LockedWheel, ...],
    payload_sha256: str,
    requirements_sha256: str,
    wheel_manifest_sha256: str,
    source_commit: str,
    source_timestamp: str,
) -> dict[str, JSONValue]:
    """Return SPDX 2.3 JSON linked to the exact production requirements."""

    packages: list[JSONValue] = [
        {
            "SPDXID": _spdx_id("arc3"),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "name": "arc3",
            "primaryPackagePurpose": "APPLICATION",
            "supplier": "Person: Christopher D. Pang",
            "versionInfo": "0.1.0",
        },
        *[_runtime_package(wheel) for wheel in runtime_wheels],
    ]
    matplotlib_evidence = _license_for("matplotlib", "3.11.1")
    matplotlib_license_text = _installed_license_text(
        "matplotlib",
        "3.11.1",
        filename="LICENSE",
        expected_sha256=matplotlib_evidence.identity,
    )
    matplotlib_wheel = next((wheel for wheel in runtime_wheels if wheel.name == "matplotlib"), None)
    if matplotlib_wheel is None:
        raise PackagingError("runtime closure omitted matplotlib license evidence")

    pyarrow_wheel = _locked_pyarrow_linux_wheel(lock_path)
    pyarrow_version = pyarrow_wheel.version
    pyarrow_evidence = _license_for("pyarrow", pyarrow_version)
    pyarrow_comment = "; ".join(
        f"{source} sha256:{identity}"
        for source, identity in (
            (pyarrow_evidence.source, pyarrow_evidence.identity),
            *pyarrow_evidence.additional,
        )
    )
    packages.append(
        {
            "SPDXID": _spdx_id("pyarrow-build-only"),
            "checksums": [
                {
                    "algorithm": "SHA256",
                    "checksumValue": pyarrow_wheel.sha256.removeprefix("sha256:"),
                }
            ],
            "downloadLocation": pyarrow_wheel.url,
            "filesAnalyzed": False,
            "licenseComments": (
                f"build-only Parquet validator selected for CPython 3.12 Linux x86_64; "
                f"{pyarrow_comment}"
            ),
            "licenseConcluded": pyarrow_evidence.expression,
            "licenseDeclared": pyarrow_evidence.expression,
            "name": "pyarrow",
            "primaryPackagePurpose": "LIBRARY",
            "supplier": "Organization: Apache Software Foundation",
            "versionInfo": pyarrow_version,
        }
    )
    hatchling_build_dependencies = (
        "hatchling",
        "pathspec",
        "pluggy",
        "tomlkit",
        "trove-classifiers",
    )
    packages.extend(_build_only_package(lock_path, name) for name in hatchling_build_dependencies)
    packages.append(
        {
            "SPDXID": _spdx_id("uv-build-tool"),
            "downloadLocation": "https://pypi.org/project/uv/0.12.5/",
            "filesAnalyzed": False,
            "licenseComments": (
                "build tool pinned by tool.uv.required-version; LICENSE-APACHE sha256:"
                "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4; "
                "LICENSE-MIT sha256:"
                "860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c"
            ),
            "licenseConcluded": "Apache-2.0 OR MIT",
            "licenseDeclared": "Apache-2.0 OR MIT",
            "name": "uv",
            "primaryPackagePurpose": "APPLICATION",
            "supplier": "Organization: Astral Software Inc.",
            "versionInfo": "0.12.5",
        }
    )
    packages.append(
        {
            "SPDXID": _spdx_id("arc-agi-3-agents-platform"),
            "downloadLocation": f"git+https://github.com/arcprize/ARC-AGI-3-Agents@{AGENTS_COMMIT}",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceLocator": "pkg:github/arcprize/ARC-AGI-3-Agents@" + AGENTS_COMMIT,
                    "referenceType": "purl",
                }
            ],
            "filesAnalyzed": False,
            "licenseComments": (
                "platform-supplied external component; pinned LICENSE Git blob "
                "d8e1cd42ac40338c6c76a8a6ac18eea0eaf95fbe"
            ),
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "ARC-AGI-3-Agents",
            "primaryPackagePurpose": "LIBRARY",
            "supplier": "Organization: ARC Prize Foundation",
            "versionInfo": AGENTS_COMMIT,
        }
    )

    relationships: list[JSONValue] = [
        {
            "relatedSpdxElement": _spdx_id("arc3"),
            "relationshipType": "DESCRIBES",
            "spdxElementId": "SPDXRef-DOCUMENT",
        },
        {
            "relatedSpdxElement": _spdx_id("arc3"),
            "relationshipType": "BUILD_DEPENDENCY_OF",
            "spdxElementId": _spdx_id("pyarrow-build-only"),
        },
        {
            "relatedSpdxElement": _spdx_id("arc3"),
            "relationshipType": "BUILD_DEPENDENCY_OF",
            "spdxElementId": _spdx_id("uv-build-tool"),
        },
        {
            "relatedSpdxElement": _spdx_id("arc-agi-3-agents-platform"),
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": _spdx_id("arc3"),
        },
    ]
    relationships.extend(
        {
            "relatedSpdxElement": _spdx_id("arc3"),
            "relationshipType": "BUILD_DEPENDENCY_OF",
            "spdxElementId": _spdx_id(f"{name}-build-only"),
        }
        for name in hatchling_build_dependencies
    )
    relationships.append(
        {
            "relatedSpdxElement": _spdx_id("hatchling-build-only"),
            "relationshipType": "BUILD_DEPENDENCY_OF",
            "spdxElementId": _spdx_id("packaging"),
        }
    )
    relationships.extend(
        {
            "relatedSpdxElement": _spdx_id(wheel.name),
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": _spdx_id("arc3"),
        }
        for wheel in runtime_wheels
    )

    namespace_seed = sha256_bytes(
        (
            f"{payload_sha256}\0{requirements_sha256}\0{wheel_manifest_sha256}\0"
            f"{source_commit}\0{lock_path.read_text(encoding='utf-8')}"
        ).encode()
    ).removeprefix("sha256:")
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "annotations": [
            {
                "annotationDate": source_timestamp,
                "annotationType": "OTHER",
                "annotator": "Tool: ARC3 first-party deterministic packager",
                "comment": (
                    f"runtime requirements {requirements_sha256}; wheel manifest "
                    f"{wheel_manifest_sha256}; first-party payload {payload_sha256}"
                ),
            }
        ],
        "creationInfo": {
            "created": source_timestamp,
            "creators": [
                "Person: Christopher D. Pang",
                "Tool: ARC3 first-party deterministic packager",
            ],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"https://github.com/Grativy6/ARC3/spdx/{namespace_seed}",
        "hasExtractedLicensingInfos": [
            {
                "extractedText": matplotlib_license_text,
                "licenseId": "LicenseRef-Matplotlib-3.11.1-Composite",
                "name": "Matplotlib 3.11.1 distribution license and bundled notices",
                "seeAlsos": [matplotlib_wheel.url],
            }
        ],
        "name": "ARC3 offline Kaggle candidate runtime SBOM",
        "packages": packages,
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
    }


__all__ = ["AGENTS_COMMIT", "build_spdx_sbom", "verify_wheelhouse_license_evidence"]
