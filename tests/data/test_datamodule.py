"""Unit tests for DataModule."""

import os
from typing import List, Any, Dict, Tuple
import pandas as pd
import sqlite3
import pytest
from torch.utils.data import SequentialSampler

from graphnet.constants import EXAMPLE_DATA_DIR
from graphnet.data.constants import FEATURES, TRUTH
from graphnet.data.dataset import SQLiteDataset, ParquetDataset
from graphnet.data.datamodule import GraphNeTDataModule
from graphnet.models.detector import IceCubeDeepCore
from graphnet.models.graphs import KNNGraph
from graphnet.models.graphs.nodes import NodesAsPulses
from graphnet.training.utils import save_selection


@pytest.fixture
def dataset_ref(request: pytest.FixtureRequest) -> pytest.FixtureRequest:
    """Return the dataset reference."""
    return request.param


@pytest.fixture
def dataset_setup(dataset_ref: pytest.FixtureRequest) -> tuple:
    """Set up the dataset for testing.

    Args:
        dataset_ref: The dataset reference.

    Returns:
        A tuple with the dataset reference, dataset kwargs, and dataloader kwargs.
    """
    # Grab public dataset paths
    data_path = (
        f"{EXAMPLE_DATA_DIR}/sqlite/prometheus/prometheus-events.db"
        if dataset_ref is SQLiteDataset
        else f"{EXAMPLE_DATA_DIR}/parquet/prometheus/prometheus-events.parquet"
    )

    # Setup basic inputs; can be altered by individual tests
    graph_definition = KNNGraph(
        detector=IceCubeDeepCore(),
        node_definition=NodesAsPulses(),
        nb_nearest_neighbours=8,
        input_feature_names=FEATURES.DEEPCORE,
    )

    dataset_kwargs = {
        "truth_table": "mc_truth",
        "pulsemaps": "total",
        "truth": TRUTH.PROMETHEUS,
        "features": FEATURES.PROMETHEUS,
        "path": data_path,
        "graph_definition": graph_definition,
    }

    dataloader_kwargs = {"batch_size": 2, "num_workers": 1}

    return dataset_ref, dataset_kwargs, dataloader_kwargs


@pytest.fixture
def selection() -> List[int]:
    """Return a selection."""
    return [1, 2, 3, 4, 5]


@pytest.fixture
def file_path(tmpdir: str) -> str:
    """Return a file path."""
    return os.path.join(tmpdir, "selection.csv")


def test_save_selection(selection: List[int], file_path: str) -> None:
    """Test `save_selection` function."""
    save_selection(selection, file_path)

    assert os.path.exists(file_path)

    with open(file_path, "r") as f:
        content = f.read()
        assert content.strip() == "1,2,3,4,5"


@pytest.mark.parametrize(
    "dataset_ref", [SQLiteDataset, ParquetDataset], indirect=True
)
def test_single_dataset_without_selections(
    dataset_setup: Tuple[Any, Dict[str, Any], Dict[str, int]]
) -> None:
    """Verify GraphNeTDataModule behavior when no test selection is provided.

    Args:
        dataset_setup: Tuple with dataset reference, dataset arguments, and dataloader arguments.

    Raises:
        Exception: If the test dataloader is accessed without providing a test selection.
    """
    dataset_ref, dataset_kwargs, dataloader_kwargs = dataset_setup

    # Only training_dataloader args
    # Default values should be assigned to validation dataloader
    dm = GraphNeTDataModule(
        dataset_reference=dataset_ref,
        dataset_args=dataset_kwargs,
        train_dataloader_kwargs=dataloader_kwargs,
    )

    train_dataloader = dm.train_dataloader()
    val_dataloader = dm.val_dataloader()
    print(dm.test_dataloader, "here")

    with pytest.raises(Exception):
        # should fail because we provided no test selection
        test_dataloader = dm.test_dataloader()  # noqa
    # validation loader should have shuffle = False by default
    assert isinstance(val_dataloader.sampler, SequentialSampler)
    # Should have identical batch_size
    assert val_dataloader.batch_size != train_dataloader.batch_size
    # Training dataloader should contain more batches
    assert len(train_dataloader) > len(val_dataloader)


def extract_all_events_ids(
    file_path: str, dataset_kwargs: Dict[str, Any]
) -> List[int]:
    """Extract all available event ids."""
    if file_path.endswith(".parquet"):
        selection = pd.read_parquet(file_path)["event_id"].to_numpy().tolist()
    elif file_path.endswith(".db"):
        with sqlite3.connect(file_path) as conn:
            query = f'SELECT event_no FROM {dataset_kwargs["truth_table"]}'
            selection = (
                pd.read_sql(query, conn)["event_no"].to_numpy().tolist()
            )
    else:
        raise AssertionError(
            f"File extension not accepted: {file_path.split('.')[-1]}"
        )
    return selection


@pytest.mark.parametrize(
    "dataset_ref", [SQLiteDataset, ParquetDataset], indirect=True
)
def test_single_dataset_with_selections(
    dataset_setup: Tuple[Any, Dict[str, Any], Dict[str, int]]
) -> None:
    """Test that selection functionality of DataModule behaves as expected.

    Args:
        dataset_setup (Tuple[Any, Dict[str, Any], Dict[str, int]]): A tuple containing the dataset reference,
            dataset arguments, and dataloader arguments.

    Returns:
        None
    """
    # extract all events
    dataset_ref, dataset_kwargs, dataloader_kwargs = dataset_setup
    file_path = dataset_kwargs["path"]
    selection = extract_all_events_ids(
        file_path=file_path, dataset_kwargs=dataset_kwargs
    )

    test_selection = selection[0:10]
    train_val_selection = selection[10:]

    # Only training_dataloader args
    # Default values should be assigned to validation dataloader
    dm = GraphNeTDataModule(
        dataset_reference=dataset_ref,
        dataset_args=dataset_kwargs,
        train_dataloader_kwargs=dataloader_kwargs,
        selection=train_val_selection,
        test_selection=test_selection,
    )

    train_dataloader = dm.train_dataloader()
    val_dataloader = dm.val_dataloader()
    test_dataloader = dm.test_dataloader()

    # Check that the training and validation dataloader contains
    # the same number of events as was given in the selection.
    assert len(train_dataloader.dataset) + len(val_dataloader.dataset) == len(train_val_selection)  # type: ignore
    # Check that the number of events in the test dataset is equal to the
    # number of events given in the selection.
    assert len(test_dataloader.dataset) == len(test_selection)  # type: ignore
    # Training dataloader should have more batches
    assert len(train_dataloader) > len(val_dataloader)
