# data — course data goes here (not in the repo)

The product photos, test images and ad video are course-provided files and are **not committed** (see `.gitignore`).

Unzip the course's `data.zip` here so the folder looks like:

```
data/
├── products/       # product photos (*.jpg) used to build catalogue.json
├── test_images/    # 4 test photos; the filename says whether a product is present (_true / _false)
└── videos/         # ad_humble.mp4, the ad scored for each customer profile
```

`catalogue.json` (already built from the photos) is committed, so product identification can run without rebuilding it.
