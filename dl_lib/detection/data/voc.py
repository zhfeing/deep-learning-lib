import os
from typing import Callable, Tuple, List
import logging
import xml.etree.ElementTree as ET

import tqdm
from PIL.Image import Image
import numpy as np

from torch import FloatTensor, LongTensor
from torch.utils.data.dataset import Dataset
from torchvision.datasets.utils import verify_str_arg

from .detection_dataset import DetectionDataset


VOC_MEAN = [0.485, 0.456, 0.406]
VOC_STD = [0.229, 0.224, 0.225]
# VOC_MEAN = [104, 117, 123]
# VOC_STD = [1, 1, 1]


class VOCPartialDataset(DetectionDataset):
    """
    Pascal VOC <http://host.robots.ox.ac.uk/pascal/VOC/> Detection Dataset.
    """
    CLASSES = (
        "aeroplane", "bicycle", "bird", "boat",
        "bottle", "bus", "car", "cat", "chair",
        "cow", "diningtable", "dog", "horse",
        "motorbike", "person", "pottedplant",
        "sheep", "sofa", "train", "tvmonitor"
    )

    def __init__(
            self,
            root: str,
            split: str = "trainval",
            version: str = "2007",
            resize: Tuple[int] = (300, 300),
            augmentations: Callable[[Image, FloatTensor, LongTensor], Tuple[Image, FloatTensor, LongTensor]] = None,
    ):
        super().__init__(resize, augmentations)
        self.keep_difficult = not("train" in split)

        verify_str_arg(version, "version", ("2007", "2012"))
        verify_str_arg(split, "split", ("train", "val", "test", "trainval"))

        self.logger = logging.getLogger("VOCDetection")
        # parse folders
        sub_dir = "VOC{}".format(version)
        self.root = os.path.expanduser(os.path.join(root, sub_dir))
        # path to image folder, e.g. VOC2007/train2017
        self.image_folder = os.path.join(self.root, "JPEGImages")
        annotation_folder = os.path.join(self.root, "Annotations")

        # read split file
        split_fp = os.path.join(self.root, "ImageSets", "Main", "{}.txt".format(split))
        if not os.path.isfile(split_fp):
            raise Exception("Split file {} is not found, note that there is no test.txt for VOC2012")
        with open(split_fp, "r") as f:
            file_names = [x.strip() for x in f.readlines()]

        self.img_sub_folder = os.path.join(self.root, "JPEGImages")

        self.difficult = dict()
        self.logger.info("Parsing VOC%s %s dataset...", version, split)
        self._init_dataset(file_names, annotation_folder)
        self.logger.info("Parsing VOC%s %s dataset done", version, split)

    def _get_annotation(self, annotation_fp: str):
        objects = ET.parse(annotation_fp).findall("object")
        boxes = []
        labels = []
        is_difficult = []
        for obj in objects:
            class_name = obj.find('name').text.lower().strip()
            bbox = obj.find('bndbox')
            # VOC dataset format follows Matlab, in which indexes start from 0
            x1 = int(bbox.find('xmin').text) - 1
            y1 = int(bbox.find('ymin').text) - 1
            x2 = int(bbox.find('xmax').text) - 1
            y2 = int(bbox.find('ymax').text) - 1
            # convert to xywh
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            labels.append(self.label_map[class_name])
            is_difficult.append(int(obj.find('difficult').text))

        return np.array(boxes), np.array(labels), np.array(is_difficult, dtype=np.bool)

    def _init_dataset(self, file_names: List[str], annotation_folder):
        # 0 stand for the background
        cnt = 0
        self.label_info[cnt] = "background"
        for cat in self.CLASSES:
            cnt += 1
            self.label_map[cat] = cnt
            self.label_info[cnt] = cat

        # build inference for images
        for img_id in file_names:
            if img_id in self.images:
                raise Exception("duplicated image record")
            self.images[img_id] = (img_id + ".jpg", [])

        # read bboxes
        self.logger.info("Reading annotations...")
        for img_id in tqdm.tqdm(file_names):
            annotation_fp = os.path.join(annotation_folder, img_id + ".xml")
            boxes, labels, is_difficult = self._get_annotation(annotation_fp)
            if not self.keep_difficult:
                boxes = boxes[~is_difficult]
                labels = labels[~is_difficult]
                is_difficult = is_difficult[~is_difficult]
            boxes = boxes.tolist()
            labels = labels.tolist()
            is_difficult = is_difficult.tolist()
            boxes = list((a, b) for a, b in zip(boxes, labels))
            self.images[img_id][1].extend(boxes)
            self.difficult[img_id] = is_difficult
        self.logger.info("Reading annotations done")

        for k, v in list(self.images.items()):
            # remove image with no annotations
            if len(v[1]) == 0:
                self.images.pop(k)

        self.img_keys = list(self.images.keys())
        self.dataset_mean = VOC_MEAN
        self.dataset_std = VOC_STD

    def other_info(self, img_id: int):
        return dict(difficult=self.difficult[img_id])

    # def __getitem__(self, index: int):
    #     """
    #     Return image, image_id, img_size (hxw), list of bounding boxes and list of bounding box labels
    #     Guarantee: bound boxes has more than one elements
    #     """
    #     import cv2
    #     import torch

    #     img_id = self.img_keys[index]
    #     image_name, bboxes = self.images[img_id]

    #     img = cv2.imread(os.path.join(self.img_sub_folder, image_name))
    #     img_h = img.shape[0]
    #     img_w = img.shape[1]

    #     bbox_sizes = []
    #     bbox_labels = []

    #     for (x, y, w, h), bbox_label in bboxes:
    #         right = x + w
    #         bottom = y + h
    #         # normalize
    #         bbox_size = (x / img_w, y / img_h, right / img_w, bottom / img_h)
    #         bbox_sizes.append(bbox_size)
    #         bbox_labels.append(bbox_label)

    #     bbox_sizes = torch.tensor(bbox_sizes, dtype=torch.float)
    #     bbox_labels = torch.tensor(bbox_labels, dtype=torch.long)

    #     if self.augmentations is not None:
    #         img, bbox_sizes, bbox_labels = self.augmentations(img, bbox_sizes, bbox_labels)

    #     img = cv2.resize(img, tuple(self.resize)).astype(np.float32)
    #     img -= VOC_MEAN
    #     img = img[..., (2, 1, 0)]
    #     img = torch.tensor(img).permute(2, 0, 1)

    #     info = dict(
    #         img_id=img_id,
    #         size=(img_h, img_w)
    #     )
    #     info.update(self.other_info(img_id))
    #     return img, bbox_sizes, bbox_labels, info


class VOC2012Dataset(Dataset):
    """
    Combined VOC2007 and VOC2012 partial
    """
    def __init__(self):
        pass
