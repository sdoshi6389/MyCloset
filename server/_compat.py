"""Import-time compatibility shims. Import this BEFORE importing basicsr/realesrgan.

`basicsr` (<=1.4.2, pulled in by realesrgan) imports
`torchvision.transforms.functional_tensor`, which torchvision >=0.17 removed.
We run torchvision 0.22, so we recreate that module here — aliasing the one
function basicsr actually needs to its current location — so the import succeeds
without hand-patching the installed package.
"""
import sys
import types

_NAME = "torchvision.transforms.functional_tensor"

if _NAME not in sys.modules:
    try:
        from torchvision.transforms.functional import rgb_to_grayscale

        _shim = types.ModuleType(_NAME)
        _shim.rgb_to_grayscale = rgb_to_grayscale
        sys.modules[_NAME] = _shim
    except Exception:
        # torchvision layout changed or unavailable — let the real import error
        # surface downstream rather than masking it here.
        pass
