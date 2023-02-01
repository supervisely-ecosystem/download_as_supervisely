import os
import supervisely as sly
from supervisely.api.module_api import ApiField
from supervisely.io.fs import get_file_ext
from distutils import util

from dotenv import load_dotenv


if sly.is_development():
    load_dotenv("local.env")
    load_dotenv(os.path.expanduser("~/supervisely.env"))


mode = os.environ["modal.state.download"]
replace_method = bool(util.strtobool(os.environ["modal.state.fixExtension"]))
batch_size = 10
STORAGE_DIR = sly.app.get_data_dir()


def ours_convert_json_info(self, info: dict, skip_missing=True):
    if info is None:
        return None
    temp_ext = None
    field_values = []
    for field_name in self.info_sequence():
        if field_name == ApiField.EXT:
            continue
        if skip_missing is True:
            val = info.get(field_name, None)
        else:
            val = info[field_name]
        field_values.append(val)
        if field_name == ApiField.MIME:
            temp_ext = val.split("/")[1]
            field_values.append(temp_ext)
    for idx, field_name in enumerate(self.info_sequence()):
        if field_name == ApiField.NAME:
            cur_ext = get_file_ext(field_values[idx]).replace(".", "").lower()
            if not cur_ext:
                field_values[idx] = "{}.{}".format(field_values[idx], temp_ext)
                break
            if temp_ext == "jpeg" and cur_ext in ["jpg", "jpeg", "mpo"]:
                break
            if temp_ext != cur_ext and cur_ext is not None:
                pass
            break
    return self.InfoType(*field_values)


if replace_method:
    sly.logger.debug("change SDK method")
    sly.api.image_api.ImageApi._convert_json_info = ours_convert_json_info


def download_json_plus_images(api, project, dataset_ids):
    sly.logger.info("DOWNLOAD_PROJECT", extra={"title": project.name})
    download_dir = os.path.join(STORAGE_DIR, f"{project.id}_{project.name}")
    sly.download_project(
        api,
        project.id,
        download_dir,
        dataset_ids=dataset_ids,
        log_progress=True,
        batch_size=batch_size,
    )
    sly.logger.info("Project {!r} has been successfully downloaded.".format(project.name))


def download_only_json(api, project, dataset_ids):
    sly.logger.info("DOWNLOAD_PROJECT", extra={"title": project.name})
    download_dir = os.path.join(STORAGE_DIR, f"{project.id}_{project.name}")
    sly.fs.mkdir(download_dir)
    meta_json = api.project.get_meta(project.id)
    sly.io.json.dump_json_file(meta_json, os.path.join(download_dir, "meta.json"))

    total_images = 0
    dataset_info = (
        [api.dataset.get_info_by_id(ds_id) for ds_id in dataset_ids]
        if (dataset_ids is not None)
        else api.dataset.get_list(project.id)
    )

    for dataset in dataset_info:
        ann_dir = os.path.join(download_dir, dataset.name, "ann")
        sly.fs.mkdir(ann_dir)

        images = api.image.get_list(dataset.id)
        ds_progress = sly.Progress(
            "Downloading annotations for: {!r}/{!r}".format(project.name, dataset.name),
            total_cnt=len(images),
        )
        for batch in sly.batched(images, batch_size=10):
            image_ids = [image_info.id for image_info in batch]
            image_names = [image_info.name for image_info in batch]

            # download annotations in json format
            ann_infos = api.annotation.download_batch(dataset.id, image_ids)

            for image_name, ann_info in zip(image_names, ann_infos):
                sly.io.json.dump_json_file(
                    ann_info.annotation, os.path.join(ann_dir, image_name + ".json")
                )
            ds_progress.iters_done_report(len(batch))
            total_images += len(batch)

    sly.logger.info("Project {!r} has been successfully downloaded".format(project.name))
    sly.logger.info("Total number of images: {!r}".format(total_images))


class MyExport(sly.app.Export):
    def process(self, context: sly.app.Export.Context):

        api = sly.Api.from_env()

        project = api.project.get_info_by_id(id=context.project_id)
        datasets = api.dataset.get_list(project.id)
        if context.dataset_id is not None:
            dataset_ids = [context.dataset_id]
        else:
            dataset_ids = [dataset.id for dataset in datasets]

        if mode == "all":
            download_json_plus_images(api, project, dataset_ids)
        else:
            download_only_json(api, project, dataset_ids)

        download_dir = os.path.join(STORAGE_DIR, f"{project.id}_{project.name}")
        full_archive_name = str(project.id) + "_" + project.name + ".tar"
        result_archive = os.path.join(STORAGE_DIR, full_archive_name)
        sly.fs.archive_directory(download_dir, result_archive)
        sly.logger.info("Result directory is archived")

        return result_archive


app = MyExport()
app.run()
