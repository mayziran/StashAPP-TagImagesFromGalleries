import stashapi.log as log
from stashapi.stashapp import StashInterface
import sys
import json

GALLERY_PAGE_SIZE = 50
IMAGE_UPDATE_BATCH = 100


def processAll():
    exclusion_marker_tag_id = None

    if settings["excludeWithTag"]:
        exclusion_marker_tag = stash.find_tag(settings["excludeWithTag"])
        if exclusion_marker_tag:
            exclusion_marker_tag_id = exclusion_marker_tag["id"]

    query = {
        "image_count": {
            "modifier": "NOT_EQUALS",
            "value": 0,
        }
    }

    if settings["excludeOrganized"]:
        query["organized"] = False

    if exclusion_marker_tag_id:
        query["tags"] = {
            "value": [exclusion_marker_tag_id],
            "modifier": "EXCLUDES",
        }

    total_count = stash.find_galleries(
        f=query,
        filter={"page": 0, "per_page": 0},
        get_count=True,
    )[0]

    processed = 0
    page = 0

    while processed < total_count:

        log.progress(processed / total_count)

        galleries = stash.find_galleries(
            f=query,
            filter={"page": page, "per_page": GALLERY_PAGE_SIZE},
        )

        if not galleries:
            break

        for gallery in galleries:
            processGallery(gallery)
            processed += 1

        page += 1


def processGallery(gallery: dict):

    if settings["excludeWithTag"]:
        for tag in gallery["tags"]:
            if tag["name"] == settings["excludeWithTag"]:
                return

    if settings["excludeOrganized"] and gallery["organized"]:
        return

    gallery_tag_ids = {t["id"] for t in gallery["tags"]}
    gallery_performer_ids = {p["id"] for p in gallery["performers"]}
    gallery_studio_id = gallery["studio"]["id"] if gallery.get("studio") else None

    if not gallery_tag_ids and not gallery_performer_ids and not gallery_studio_id:
        return

    images = stash.find_gallery_images(
        gallery["id"],
        fragment="id tags { id } performers { id } studio { id }"
    )

    if not images:
        return

    batch_ids = []
    batch_tags = set()
    batch_performers = set()
    batch_studio_id = None

    for image in images:

        image_tag_ids = {t["id"] for t in image["tags"]}
        image_performer_ids = {p["id"] for p in image["performers"]}
        image_studio_id = image["studio"]["id"] if image.get("studio") else None

        new_tag_ids = gallery_tag_ids - image_tag_ids
        new_performer_ids = gallery_performer_ids - image_performer_ids
        new_studio_id = gallery_studio_id if gallery_studio_id and gallery_studio_id != image_studio_id else None

        if not new_tag_ids and not new_performer_ids and not new_studio_id:
            continue

        batch_ids.append(image["id"])
        batch_tags.update(new_tag_ids)
        batch_performers.update(new_performer_ids)
        batch_studio_id = new_studio_id or batch_studio_id

        if len(batch_ids) >= IMAGE_UPDATE_BATCH:
            sendImageBatch(batch_ids, batch_tags, batch_performers, batch_studio_id)
            batch_ids = []
            batch_tags = set()
            batch_performers = set()
            batch_studio_id = None

    if batch_ids:
        sendImageBatch(batch_ids, batch_tags, batch_performers, batch_studio_id)


def sendImageBatch(image_ids, tag_ids, performer_ids, studio_id=None):

    update_data = {
        "ids": image_ids
    }

    if tag_ids:
        update_data["tag_ids"] = {
            "mode": "ADD",
            "ids": list(tag_ids)
        }

    if performer_ids:
        update_data["performer_ids"] = {
            "mode": "ADD",
            "ids": list(performer_ids)
        }

    if studio_id:
        update_data["studio_id"] = studio_id

    log.info(f"Updating {len(image_ids)} images")

    stash.update_images(update_data)


json_input = json.loads(sys.stdin.read())

FRAGMENT_SERVER = json_input["server_connection"]
stash = StashInterface(FRAGMENT_SERVER)

config = stash.get_configuration()

settings = {
    "excludeWithTag": "",
    "excludeOrganized": False
}

if "tagImagesFromGalleries" in config["plugins"]:
    settings.update(config["plugins"]["tagImagesFromGalleries"])


if "mode" in json_input["args"]:

    if "processAll" in json_input["args"]["mode"]:
        processAll()

elif "hookContext" in json_input["args"]:

    hook = json_input["args"]["hookContext"]
    gallery_id = hook["id"]

    if (
        hook["type"] in ["Gallery.Update.Post", "Gallery.Create.Post"]
        and "inputFields" in hook
        and len(hook["inputFields"]) > 2
    ):
        gallery = stash.find_gallery(gallery_id)
        processGallery(gallery)