# lightning imports
import pytorch_lightning as pl

# hydra imports
from omegaconf import DictConfig, OmegaConf
from hydra.utils import get_original_cwd, to_absolute_path
from hydra.utils import log

# logger imports
import wandb
from pytorch_lightning.loggers.wandb import WandbLogger

# from pytorch_lightning.loggers.neptune import NeptuneLogger
# from pytorch_lightning.loggers.comet import CometLogger
# from pytorch_lightning.loggers.mlflow import MLFlowLogger
# from pytorch_lightning.loggers.tensorboard import TensorBoardLogger

# rich imports
from rich.syntax import Syntax
from rich.tree import Tree
from rich import print

# normal imports
from typing import List
import warnings
import logging


def extras(config: DictConfig):
    """A couple of optional utilities, controlled with variables in main config file.
    Simply delete those if you don' want them.

    Args:
        config (DictConfig): [description]
    """

    # [OPTIONAL] Disable python warnings if <disable_warnings=True>
    if config.get("disable_warnings"):
        log.info(f"Disabling python warnings! <{config.disable_warnings=}>")
        warnings.filterwarnings("ignore")

    # [OPTIONAL] Disable Lightning logs if <disable_lightning_logs=True>
    if config.get("disable_lightning_logs"):
        log.info(f"Disabling lightning logs! {config.disable_lightning_logs=}>")
        logging.getLogger("lightning").setLevel(logging.ERROR)

    # [OPTIONAL] Force debugger friendly configuration if <trainer.fast_dev_run=True>
    if config.trainer.get("fast_dev_run"):
        log.info(
            f"Forcing debugger friendly configuration! "
            f"<{config.trainer.fast_dev_run=}>"
        )
        # Debuggers don't like GPUs or multiprocessing
        if config.trainer.get("gpus"):
            config.trainer.gpus = 0
        if config.datamodule.get("num_workers"):
            config.datamodule.num_workers = 0

    # [OPTIONAL] Pretty print config using Rich library if <print_config=True>
    if config.get("print_config"):
        log.info(f"Pretty printing config with Rich! <{config.print_config=}>")
        print_config(config)


def print_config(config: DictConfig):
    """Prints content of Hydra config using Rich library.

    Args:
        config (DictConfig): [description]
    """

    # TODO print main config path and experiment config path
    # directory = to_absolute_path("configs/config.yaml")
    # print(f"Main config path: [link file://{directory}]{directory}")

    style = "dim"

    tree = Tree(f":gear: TRAINING CONFIG", style=style, guide_style=style)

    trainer = OmegaConf.to_yaml(config["trainer"], resolve=True)
    trainer_branch = tree.add("Trainer", style=style, guide_style=style)
    trainer_branch.add(Syntax(trainer, "yaml"))

    model = OmegaConf.to_yaml(config["model"], resolve=True)
    model_branch = tree.add("Model", style=style, guide_style=style)
    model_branch.add(Syntax(model, "yaml"))

    datamodule = OmegaConf.to_yaml(config["datamodule"], resolve=True)
    datamodule_branch = tree.add("Datamodule", style=style, guide_style=style)
    datamodule_branch.add(Syntax(datamodule, "yaml"))

    callbacks_branch = tree.add("Callbacks", style=style, guide_style=style)
    if "callbacks" in config:
        for cb_name, cb_conf in config["callbacks"].items():
            cb = callbacks_branch.add(cb_name, style=style, guide_style=style)
            cb.add(Syntax(OmegaConf.to_yaml(cb_conf, resolve=True), "yaml"))
    else:
        callbacks_branch.add("None")

    logger_branch = tree.add("Logger", style=style, guide_style=style)
    if "logger" in config:
        for lg_name, lg_conf in config["logger"].items():
            lg = logger_branch.add(lg_name, style=style, guide_style=style)
            lg.add(Syntax(OmegaConf.to_yaml(lg_conf, resolve=True), "yaml"))
    else:
        logger_branch.add("None")

    seed = config.get("seed", "None")
    seed_branch = tree.add(f"Seed", style=style, guide_style=style)
    seed_branch.add(str(seed) + "\n")

    print(tree)


def log_hparams_to_all_loggers(
    config: DictConfig,
    model: pl.LightningModule,
    datamodule: pl.LightningDataModule,
    trainer: pl.Trainer,
    callbacks: List[pl.Callback],
    logger: List[pl.loggers.LightningLoggerBase],
):
    """This method controls which parameters from Hydra config are saved by Lightning loggers.

    Args:
        config (DictConfig): [description]
        model (pl.LightningModule): [description]
        datamodule (pl.LightningDataModule): [description]
        trainer (pl.Trainer): [description]
        callbacks (List[pl.Callback]): [description]
        logger (List[pl.loggers.LightningLoggerBase]): [description]
    """

    hparams = {}

    # save all params of model, datamodule and trainer
    hparams.update(config["model"])
    hparams.update(config["datamodule"])
    hparams.update(config["trainer"])
    hparams.pop("_target_")

    # save seed
    hparams["seed"] = config.get("seed", "None")

    # save targets
    hparams["_class_model"] = config["model"]["_target_"]
    hparams["_class_datamodule"] = config["datamodule"]["_target_"]

    # save sizes of each dataset
    if hasattr(datamodule, "data_train") and datamodule.data_train:
        hparams["train_size"] = len(datamodule.data_train)
    if hasattr(datamodule, "data_val") and datamodule.data_val:
        hparams["val_size"] = len(datamodule.data_val)
    if hasattr(datamodule, "data_test") and datamodule.data_test:
        hparams["test_size"] = len(datamodule.data_test)

    # save number of model parameters
    hparams["#params_total"] = sum(p.numel() for p in model.parameters())
    hparams["#params_trainable"] = sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    hparams["#params_not_trainable"] = sum(
        p.numel() for p in model.parameters() if not p.requires_grad
    )

    # send hparams to all loggers
    trainer.logger.log_hyperparams(hparams)


def finish(
    config: DictConfig,
    model: pl.LightningModule,
    datamodule: pl.LightningDataModule,
    trainer: pl.Trainer,
    callbacks: List[pl.Callback],
    logger: List[pl.loggers.LightningLoggerBase],
):
    """Makes sure everything closed properly.

    Args:
        config (DictConfig): [description]
        model (pl.LightningModule): [description]
        datamodule (pl.LightningDataModule): [description]
        trainer (pl.Trainer): [description]
        callbacks (List[pl.Callback]): [description]
        logger (List[pl.loggers.LightningLoggerBase]): [description]
    """

    # without this sweeps with wandb logger might crash!
    for lg in logger:
        if isinstance(lg, WandbLogger):
            wandb.finish()
