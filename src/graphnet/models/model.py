"""Base class(es) for building models."""

from abc import ABC, abstractmethod
import dill
import os.path
import re
from typing import Dict, List, Optional, Union

from pytorch_lightning import LightningModule
import torch
from torch import Tensor
from torch_geometric.data import Data

import graphnet
from graphnet.utilities.logging import LoggerMixin
from graphnet.utilities.config import Configurable, ModelConfig
from graphnet.utilities.config.parsing import (
    traverse_and_apply,
    get_all_grapnet_classes,
)


class Model(Configurable, LightningModule, LoggerMixin, ABC):
    """Base class for all models in graphnet."""

    @abstractmethod
    def forward(self, x: Union[Tensor, Data]) -> Union[Tensor, Data]:
        """Forward pass."""

    def save(self, path: str) -> None:
        """Save entire model to `path`."""
        if not path.endswith(".pth"):
            self.info(
                "It is recommended to use the .pth suffix for model files."
            )
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        torch.save(self.cpu(), path, pickle_module=dill)
        self.info(f"Model saved to {path}")

    @classmethod
    def load(cls, path: str) -> "Model":
        """Load entire model from `path`."""
        return torch.load(path, pickle_module=dill)

    def save_state_dict(self, path: str) -> None:
        """Save model `state_dict` to `path`."""
        if not path.endswith(".pth"):
            self.info(
                "It is recommended to use the .pth suffix for state_dict files."
            )
        torch.save(self.cpu().state_dict(), path)
        self.info(f"Model state_dict saved to {path}")

    def load_state_dict(
        self, path: Union[str, Dict]
    ) -> "Model":  # pylint: disable=arguments-differ
        """Load model `state_dict` from `path`."""
        if isinstance(path, str):
            state_dict = torch.load(path)
        else:
            state_dict = path
        return super().load_state_dict(state_dict)

    @classmethod
    def from_config(  # type: ignore[override]
        cls,
        source: Union[ModelConfig, str],
        trust: bool = False,
        load_modules: Optional[List[str]] = None,
    ) -> "Model":
        """Construct `Model` instance from `source` configuration.

        Arguments:
            trust: Whether to trust the ModelConfig file enough to `eval(...)`
                any lambda function expressions contained.
            load_modules: List of modules used in the definition of the model
                which, as a consequence, need to be loaded into the global
                namespace. Defaults to loading `torch`.

        Raises:
            ValueError: If the ModelConfig contains lambda functions but
                `trust = False`.
        """
        if isinstance(source, str):
            source = ModelConfig.load(source)

        assert isinstance(
            source, ModelConfig
        ), f"Argument `source` of type ({type(source)}) is not a `ModelConfig"

        # Check(s)
        if load_modules is None:
            load_modules = ["torch"]
        assert isinstance(load_modules, list)

        # Get a lookup for all classes in `graphnet`
        namespace_classes = get_all_grapnet_classes(
            graphnet.data, graphnet.models, graphnet.training
        )

        # Load any additional modules into the global namespace
        for module in load_modules:
            assert re.match("^[a-zA-Z_]+$", module) is not None
            if module in globals():
                continue
            exec(f"import {module}", globals())

        # Parse potential ModelConfig arguments
        arguments = dict(**source.arguments)
        arguments = traverse_and_apply(
            arguments,
            source._deserialise,
            fn_kwargs={"trust": trust},
        )

        # Construct model based on arguments
        return namespace_classes[source.class_name](**arguments)
