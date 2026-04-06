import pathlib
import shutil

import requests

STUFF = {
    "htmx.org@2.0.8": ["dist/htmx.min.js"],
    "htmx-ext-response-targets@2.0.4": ["dist/response-targets.min.js"],
    "bootstrap@5.3.8": [
        "dist/css/bootstrap.min.css",
        "dist/js/bootstrap.bundle.min.js",
    ],
    "bootstrap-icons@1.13.1": [
        "font/bootstrap-icons.min.css",
        "font/fonts/bootstrap-icons.woff",
        "font/fonts/bootstrap-icons.woff2",
    ],
}

self_path = pathlib.Path(__file__)
root_dir = self_path.parent.parent
vendor_dir = root_dir / "src/reader/_app/static/vendor"
url_fmt = "https://cdn.jsdelivr.net/npm/{package}/{path}"

shutil.rmtree(vendor_dir, ignore_errors=True)
vendor_dir.mkdir(parents=True)
(vendor_dir / "README").write_text(f"maintained by {self_path.name}")

for package, paths in STUFF.items():
    for path in paths:

        src = url_fmt.format(package=package, path=path)
        response = requests.get(src)
        response.raise_for_status()

        dst = vendor_dir.joinpath(package, *pathlib.PosixPath(path).parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(response.content)

        print(f"{package} {path} done")
