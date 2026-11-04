"""Compile the reviewed vault with pinned solc-js; no npm install or scripts.

solc-js wrapper: MIT. Included Solidity compiler: GPL-3.0. Build tools remain
outside the repository; the emitted contract artifact is KiteShield's MIT code.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

INTEGRITY = "9Srk/gndtBmoUbg4CE6ypAzPQlElv8ntbnl6SigUBAzgXKn35v87sj04uZeoZWjtDkdzT0qKFcIo/wl63UMxdw=="


def main():
    root = Path(__file__).resolve().parents[2]
    tools = Path.home() / ".local/share/kiteshield/solc-js-0.8.30"
    tools.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = tools / "solc-0.8.30.tgz"
    if not archive.exists():
        with urllib.request.urlopen("https://registry.npmjs.org/solc/-/solc-0.8.30.tgz", timeout=60) as source:  # noqa: S310 -- fixed official package registry
            archive.write_bytes(source.read())
    if base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode() != INTEGRITY:
        raise RuntimeError("Compiler package integrity mismatch")
    if not (tools / "package/soljson.js").exists():
        with tarfile.open(archive) as bundle:
            bundle.extractall(tools, filter="data")
    source = root / "spikes/guarded-vault/src/GuardedVault.sol"
    spec = {"language": "Solidity", "sources": {"GuardedVault.sol": {"content": source.read_text()}},
            "settings": {"optimizer": {"enabled": True, "runs": 200}, "evmVersion": "cancun",
                         "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object", "evm.deployedBytecode"]}}}}
    program = "const s=require(process.argv[1]);const fs=require('node:fs');const version=s.cwrap('solidity_version','string',[])();const output=JSON.parse(s.cwrap('solidity_compile','string',['string','number','number'])(fs.readFileSync(0,'utf8'),0,0));process.stdout.write(JSON.stringify({version,output}));"
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Installed Node required")
    result = subprocess.run([node, "-e", program, str(tools / "package/soljson.js")],  # noqa: S603 -- fixed pinned compiler, no shell
        input=json.dumps(spec), text=True, capture_output=True, check=True,
        env={k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ})
    data = json.loads(result.stdout)
    if not data["version"].startswith("0.8.30+commit.73712a01"):
        raise RuntimeError("Compiler version mismatch")
    errors = [row["formattedMessage"] for row in data["output"].get("errors", []) if row["severity"] == "error"]
    if errors:
        raise RuntimeError("\n".join(errors))
    contract = data["output"]["contracts"]["GuardedVault.sol"]["GuardedVault"]
    artifact = {"compiler": data["version"], "compiler_package_integrity_sha512": INTEGRITY,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "abi": contract["abi"], "bytecode": "0x" + contract["evm"]["bytecode"]["object"],
                "runtime": contract["evm"]["deployedBytecode"]["object"],
                "immutable_references": contract["evm"]["deployedBytecode"]["immutableReferences"]}
    target = root / "backend/app/contracts/guarded_vault.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2))
    print(json.dumps({"artifact": str(target), "compiler": data["version"], "source_sha256": artifact["source_sha256"]}))


if __name__ == "__main__":
    main()
