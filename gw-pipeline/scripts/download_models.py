#!/usr/bin/env python3
"""Download and verify DL model files for GravitationalWave platform.

Usage:
    python scripts/download_models.py              # Download all models
    python scripts/download_models.py --verify     # Verify existing models
    python scripts/download_models.py --list       # List available models

Models:
    zoobot_encoder_greyscale  (57 MB) — Zoobot ConvNeXt-Nano greyscale encoder
    morphology_archetypes     (<1 KB) — Reference embeddings for cosine-similarity classification

License: Zoobot pretrained weights are GPL-3.0. See https://github.com/mwalmsley/zoobot
"""
import os, sys, json, hashlib, argparse, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("download_models")

# ── Configuration ───────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
MODEL_DIR = PROJECT_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

# HF mirror for China network access
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")

MODELS = {
    "zoobot_encoder_greyscale": {
        "filename": "zoobot_encoder_greyscale.onnx",
        "size_mb": 57.1,
        "sha256": "ccdd3bb4506e72a7c4672b9a04ab60ff8ca5dfed5ea8e45e9036c1f24edb0277",
        "description": "Zoobot ConvNeXt-Nano greyscale encoder -> 640-D galaxy morphology features",
        "license": "GPL-3.0",
        "hf_repo": "mwalmsley/zoobot-encoder-greyscale-convnext_nano",
        "source": "huggingface",
        "required": True,
    },
    "morphology_archetypes": {
        "filename": "morphology_archetypes.json",
        "size_mb": 0.001,
        "sha256": None,
        "description": "Reference 640-D embeddings for galaxy morphology archetypes (cosine similarity)",
        "license": "CC0 (generated data)",
        "source": "generated",
        "required": False,
    },
}


def compute_sha256(filepath: Path) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_model(name: str, info: dict) -> dict:
    filepath = MODEL_DIR / info["filename"]
    result = {
        "name": name, "filepath": str(filepath),
        "exists": filepath.exists(), "valid": False,
        "size_mb": 0, "sha256": None, "issues": [],
    }
    if not result["exists"]:
        result["issues"].append("FILE_MISSING")
        return result
    result["size_mb"] = round(filepath.stat().st_size / (1024 * 1024), 2)
    result["sha256"] = compute_sha256(filepath)
    if info.get("sha256") and result["sha256"] != info["sha256"]:
        result["issues"].append(f"SHA256_MISMATCH")
    else:
        result["valid"] = True
    return result


def download_zoobot_encoder() -> bool:
    info = MODELS["zoobot_encoder_greyscale"]
    output_path = MODEL_DIR / info["filename"]

    if output_path.exists():
        sha = compute_sha256(output_path)
        if sha == info["sha256"]:
            log.info("zoobot_encoder_greyscale already downloaded and verified")
            return True
        log.warning("Existing file has wrong checksum, re-downloading...")

    # Attempt: Download from HuggingFace mirror
    try:
        if HF_ENDPOINT:
            os.environ["HF_ENDPOINT"] = HF_ENDPOINT
            log.info("Using HF mirror: %s", HF_ENDPOINT)
        from huggingface_hub import hf_hub_download
        log.info("Downloading Zoobot encoder from %s...", info["hf_repo"])
        weights_path = hf_hub_download(
            repo_id=info["hf_repo"],
            filename="pytorch_model.bin",
            cache_dir=str(MODEL_DIR / ".cache"),
        )
        log.info("Downloaded weights to: %s", weights_path)

        import torch, timm
        log.info("Converting to ONNX...")
        model = timm.create_model("convnext_nano", pretrained=False, in_chans=1, num_classes=0)
        state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
        if "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        model.load_state_dict(state_dict, strict=False)
        model.eval()

        dummy = torch.randn(1, 1, 224, 224)
        torch.onnx.export(
            model, dummy, str(output_path),
            input_names=["input"], output_names=["features"],
            dynamic_axes={"input": {0: "batch"}, "features": {0: "batch"}},
            opset_version=14, do_constant_folding=True, export_params=True,
        )
        import onnx
        onnx.checker.check_model(onnx.load(str(output_path)))
        sha = compute_sha256(output_path)
        log.info("ONNX model saved: %s (SHA-256: %s...)", output_path, sha[:32])
        return True
    except Exception as e:
        log.warning("HF download failed: %s", e)

    # Fallback: build architecture-only model (random weights)
    log.warning("Building architecture-only ONNX model (NOT PRETRAINED)...")
    log.warning("Replace with pretrained weights when network is available.")
    try:
        import torch, timm
        model = timm.create_model("convnext_nano", pretrained=False, in_chans=1, num_classes=0)
        model.eval()
        dummy = torch.randn(1, 1, 224, 224)
        torch.onnx.export(
            model, dummy, str(output_path),
            input_names=["input"], output_names=["features"],
            dynamic_axes={"input": {0: "batch"}, "features": {0: "batch"}},
            opset_version=14, do_constant_folding=True, export_params=True,
        )
        log.info("Architecture-only ONNX model saved (NOT PRETRAINED)")
        return True
    except Exception as e:
        log.error("Failed to build architecture-only model: %s", e)
        return False


def generate_archetypes() -> bool:
    info = MODELS["morphology_archetypes"]
    output_path = MODEL_DIR / info["filename"]
    if output_path.exists():
        log.info("morphology_archetypes.json already exists")
        return True
    log.info("Generating placeholder archetype embeddings...")
    log.warning("These are RANDOM embeddings - replace with real survey-derived embeddings!")
    import numpy as np
    rng = np.random.RandomState(42)
    archetypes = {}
    for cls_name in ["spiral", "elliptical", "edge-on", "merger", "irregular"]:
        emb = rng.randn(640).astype(np.float32)
        emb /= np.linalg.norm(emb)
        archetypes[cls_name] = emb.tolist()
    with open(output_path, "w") as f:
        json.dump(archetypes, f, indent=2)
    log.info("Placeholder archetypes generated at %s", output_path)
    log.warning("Replace with real Zoobot embeddings of labeled DECaLS galaxies!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Download and verify DL models for GravitationalWave")
    parser.add_argument("--verify", action="store_true", help="Verify existing models without downloading")
    parser.add_argument("--list", action="store_true", help="List available models")
    parser.add_argument("--model", type=str, default=None, help="Download/verify specific model only")
    args = parser.parse_args()

    if args.list:
        print(f"\nModels directory: {MODEL_DIR}")
        print(f"{'Model':<35} {'Size':>8} {'Required':>9} {'License':>12}")
        print("-" * 70)
        for name, info in MODELS.items():
            filepath = MODEL_DIR / info["filename"]
            status = "PRESENT" if filepath.exists() else "MISSING"
            print(f"{name:<35} {info['size_mb']:>6.1f} MB {'YES' if info['required'] else 'NO':>9} {info['license']:>12}  {status}")
        print()
        return 0

    if args.verify:
        all_valid = True
        for name, info in MODELS.items():
            if args.model and name != args.model:
                continue
            result = verify_model(name, info)
            if result["valid"]:
                log.info("%s: VALID (%.1f MB)", name, result["size_mb"])
            else:
                log.error("%s: INVALID - %s", name, ", ".join(result["issues"]))
                all_valid = False
        return 0 if all_valid else 1

    # Download mode
    models_to_download = [args.model] if args.model else list(MODELS.keys())
    for model_name in models_to_download:
        if model_name not in MODELS:
            log.error("Unknown model: %s", model_name)
            continue
        info = MODELS[model_name]
        log.info("Model: %s | %s | License: %s | ~%.1f MB", model_name, info["description"], info["license"], info["size_mb"])
        if model_name == "zoobot_encoder_greyscale":
            success = download_zoobot_encoder()
        elif model_name == "morphology_archetypes":
            success = generate_archetypes()
        else:
            success = False
        log.info("%s: %s", model_name, "DONE" if success else "FAILED")

    # Final verification
    log.info("=" * 60)
    all_valid = True
    for name, info in MODELS.items():
        result = verify_model(name, info)
        if result["valid"]:
            log.info("  %s (%.1f MB)", name, result["size_mb"])
        elif name == "morphology_archetypes" and result["exists"]:
            log.info("  %s (placeholder - replace with real embeddings)", name)
        else:
            log.error("  %s: %s", name, ", ".join(result["issues"]))
            all_valid = False
    return 0 if all_valid else 1


if __name__ == "__main__":
    sys.exit(main())
