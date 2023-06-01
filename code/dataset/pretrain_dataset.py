from torch.utils.data import Dataset
import torch
import numpy as np
import random
import os
import pandas as pd
from sklearn import preprocessing


class PretrainDataset(Dataset):
    def __init__(self, file_path, num_features, patch_size, max_length, norm=None, mask_rate=0.15):
        """
        :param file_path: path to the folder of the pre-training dataset
        :param num_features: dimension of each pixel
        :param patch_size: patch size
        :param max_length: padded sequence length
        :param norm: mean and std used to normalize the input reflectance
        :param mask_rate: rate of masked timesteps
        """
        self.file_path = file_path
        self.max_length = max_length
        self.dimension = num_features
        self.patch_size = patch_size
        self.MASK_TOKEN = np.random.normal(loc=0, scale=1e-2,
                                           size=(num_features, patch_size, patch_size))
        self.mask_rate = mask_rate

        self.FileList = os.listdir(file_path)
        self.TS_num = len(self.FileList)  # number of unlabeled samples
        self.norm = norm

    def __len__(self):
        return self.TS_num

    def __getitem__(self, item):
        file = self.FileList[item]
        file = os.path.join(self.file_path, file)
        with np.load(file) as sample:
            ts_origin = sample["ts"]  # [seq_Length, band_nums, patch_size, patch_size]

            if self.norm is not None:
                m, s = self.norm
                m = np.expand_dims(m, axis=-1)
                s = np.expand_dims(s, axis=-1)
                shape = ts_origin.shape
                ts_origin = ts_origin.reshape((shape[0], shape[1], -1))
                ts_origin = (ts_origin - m) / s
                ts_origin = ts_origin.reshape(shape)
            else:
                ts_origin = ts_origin / 10000.0

            # length of the time series (varies for each sample)
            ts_length = ts_origin.shape[0]

            # padding time series to the same length
            ts_origin = np.pad(ts_origin, ((0, self.max_length - ts_length), (0, 0), (0, 0), (0, 0)),
                               mode='constant', constant_values=0.0)

            # acquisition dates of this time series
            doy = sample["doy"]  # [seq_Length, ]
            doy = np.pad(doy, (0, self.max_length - ts_length), mode='constant', constant_values=0)

            # prediction target: the center pixel (the pixel to be classified afterward)
            bert_target = np.squeeze(ts_origin[:, :, 2, 2])  # [max_Length, band_nums]

            # randomly replace some patches with a pre-defined MASK_TOKEN
            ts_masking, mask = self.random_masking(ts_origin, ts_length)

            # mask of valid observations
            bert_mask = np.zeros((self.max_length,), dtype=int)
            bert_mask[:ts_length] = 1

        output = {"bert_input": ts_masking,
                  "bert_target": bert_target,
                  "bert_mask": bert_mask,
                  "loss_mask": mask,
                  "timestamp": doy,
                  }

        return {key: torch.from_numpy(value) for key, value in output.items()}

    def random_masking(self, ts, ts_length):
        ts_masking = ts.copy()
        mask = np.zeros((self.max_length,), dtype=int)

        for i in range(ts_length):
            prob = random.random()
            if prob < self.mask_rate:
                mask[i] = 1
                ts_masking[i, :, :, :] = self.MASK_TOKEN

        return ts_masking, mask


class GWPretrainDataset(Dataset):
    def __init__(self, file_path, num_features, patch_size, max_length, norm=None, mask_rate=0.15):
        """
        :param file_path: path to the folder of the pre-training dataset
        :param num_features: dimension of each pixel
        :param patch_size: patch size
        :param max_length: padded sequence length
        :param norm: mean and std used to normalize the input reflectance
        :param mask_rate: rate of masked timesteps
        """
        self.file_path = file_path
        self.max_length = max_length
        self.dimension = num_features
        self.patch_size = patch_size
        self.MASK_TOKEN = np.random.normal(loc=0, scale=1e-2,
                                           size=(num_features, patch_size, patch_size))
        self.mask_rate = mask_rate

        self.FileList = os.listdir(file_path)
        self.TS_num = len(self.FileList)  # number of unlabeled samples
        self.norm = norm

        self.poi_ids = None
        self.poi_id_to_class = None
        self.poi_id_to_weight = None
        self.days_indices = np.arange(0, 365, 3)

        self.features = None
        self._load_features()

    def __len__(self):
        return self.TS_num

    def __getitem__(self, item):
        file = self.FileList[item]
        file = os.path.join(self.file_path, file)
        with np.load(file) as sample:
            ts_origin = sample["ts"]  # [seq_Length, band_nums, patch_size, patch_size]

            if self.norm is not None:
                m, s = self.norm
                m = np.expand_dims(m, axis=-1)
                s = np.expand_dims(s, axis=-1)
                shape = ts_origin.shape
                ts_origin = ts_origin.reshape((shape[0], shape[1], -1))
                ts_origin = (ts_origin - m) / s
                ts_origin = ts_origin.reshape(shape)
            else:
                ts_origin = ts_origin / 10000.0

            # length of the time series (varies for each sample)
            ts_length = ts_origin.shape[0]

            # padding time series to the same length
            ts_origin = np.pad(ts_origin, ((0, self.max_length - ts_length), (0, 0), (0, 0), (0, 0)),
                               mode='constant', constant_values=0.0)

            # acquisition dates of this time series
            doy = sample["doy"]  # [seq_Length, ]
            doy = np.pad(doy, (0, self.max_length - ts_length), mode='constant', constant_values=0)

            # prediction target: the center pixel (the pixel to be classified afterward)
            bert_target = np.squeeze(ts_origin[:, :, 1])  # [max_Length, band_nums]

            # randomly replace some patches with a pre-defined MASK_TOKEN
            ts_masking, mask = self.random_masking(ts_origin, ts_length)

            # mask of valid observations
            bert_mask = np.zeros((self.max_length,), dtype=int)
            bert_mask[:ts_length] = 1

        output = {"bert_input": ts_masking,
                  "bert_target": bert_target,
                  "bert_mask": bert_mask,
                  "loss_mask": mask,
                  "timestamp": doy,
                  }

        return {key: torch.from_numpy(value) for key, value in output.items()}

    def _load_features(self):
        # load data and filter by poi_ids
        data = pd.read_csv(self.file_path, header=None).rename(columns={0: "poi_id", 1: "date"})
        data = data[data["poi_id"].isin(self.poi_ids)]

        # convert date to datetime and sort by poi_id and date
        data["date"] = pd.to_datetime(data["date"])
        data.sort_values(["poi_id", "date"], inplace=True)
        data["date_index"] = data["date"].dt.dayofyear

        features = data.groupby("poi_id")[["date_index"] + list(self.bands)].agg(list)

        self.features = features.apply(
            lambda row: [np.interp(self.days_indices, row["date_index"], row[i]) for i in self.bands],
            axis=1)
        self.features = self.features.apply(lambda sample: preprocessing.scale(np.array(sample)))

    def random_masking(self, ts, ts_length):
        ts_masking = ts.copy()
        mask = np.zeros((self.max_length,), dtype=int)

        for i in range(ts_length):
            prob = random.random()
            if prob < self.mask_rate:
                mask[i] = 1
                ts_masking[i, :, :, :] = self.MASK_TOKEN

        return ts_masking, mask

