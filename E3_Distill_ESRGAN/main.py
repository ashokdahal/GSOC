"""
  Compressing GANs using Knowledge Distillation.
  Teacher GAN: ESRGAN (https://github.com/captain-pool/E2_ESRGAN)

Citation:
  @article{DBLP:journals/corr/abs-1902-00159,
    author    = {Angeline Aguinaldo and
    Ping{-}Yeh Chiang and
    Alexander Gain and
    Ameya Patil and
    Kolten Pearson and
    Soheil Feizi},
    title     = {Compressing GANs using Knowledge Distillation},
    journal   = {CoRR},
    volume    = {abs/1902.00159},
    year      = {2019},
    url       = {http://arxiv.org/abs/1902.00159},
    archivePrefix = {arXiv},
    eprint    = {1902.00159},
    timestamp = {Tue, 21 May 2019 18:03:39 +0200},
    biburl    = {https://dblp.org/rec/bib/journals/corr/abs-1902-00159},
    bibsource = {dblp computer science bibliography, https://dblp.org}
  }
"""
import os
from absl import logging
import argparse
from libs import lazy_loader
from libs import model
from libs import settings
import tensorflow as tf


def train_and_export(**kwargs):
  """ Train and Export Compressed ESRGAN
      Args:
        config: path to config file.
        logdir: path to logging directory
        modeldir: Path to store the checkpoints and exported model.
        datadir: Path to custom data directory.
        manual: Boolean to indicate if `datadir` contains Raw Files(True) / TFRecords (False)
  """
  lazy = lazy_loader.LazyLoader()

  student_settings = settings.Settings(
      kwargs["config"], use_student_settings=True)

  # Lazy importing dependencies from teacher
  lazy.import_("teacher_imports", parent="libs", return_=False)
  lazy.import_("teacher", parent="libs.models", return_=False)
  lazy.import_("train", parent="libs", return_=False)
  lazy.import_("utils", parent="libs", return_=False)
  globals().update(lazy.import_dict)
  tf.random.set_seed(10)
  teacher_settings = settings.Settings(
      student_settings["teacher_config"], use_student_settings=False)
  stats = settings.Stats(os.path.join(student_settings.path, "stats.yaml"))
  strategy = utils.SingleDeviceStrategy()

  if kwargs["tpu"]:
    cluster_resolver = tf.distribute.cluster_resolver.TPUClusterResolver(
        kwargs["tpu"])
    tf.config.experimental_connect_to_host(cluster_resolver.get_master())
    tf.tpu.experimental.initialize_tpu_system(cluster_resolver)
    strategy = tf.distribute.experimental.TPUStrategy(cluster_resolver)

  device_name = utils.assign_to_worker(kwargs["tpu"])

  with tf.device(device_name), strategy.scope():
    summary_writer = tf.summary.create_file_writer(
        os.path.join(kwargs["logdir"], "student"))
    teacher_summary_writer = tf.summary.create_file_writer(
        os.path.join(kwargs["logdir"], "teacher"))

    teacher_generator = teacher.generator(out_channel=3, first_call=False)
    teacher_discriminator = teacher.discriminator(
        batch_size=teacher_settings["batch_size"])

    student_generator = (
        model.Registry
        .models[student_settings["student_network"]]())

    hr_size = tf.cast(tf.convert_to_tensor([1] + student_settings['hr_size']), tf.float32)
    lr_size = tf.cast(hr_size * tf.convert_to_tensor([1, 1/4, 1/4, 1]), tf.int32)

    logging.debug("Initializing Convolutions")
    student_generator.unsigned_call(tf.random.normal(lr_size))

    trainer = train.Trainer(
        teacher_generator,
        teacher_discriminator,
        summary_writer,
        summary_writer_2=teacher_summary_writer,
        model_dir=kwargs["modeldir"],
        data_dir=kwargs["datadir"],
        strategy=strategy)
    phase_name = None
    if kwargs["type"].lower().startswith("comparative"):
      trainer.train_comparative(
          student_generator,
          export_only=stats.get("comparative") or kwargs["export_only"])
      if not kwargs["export_only"]:
        stats["comparative"] = True
    elif kwargs["type"].lower().startswith("adversarial"):
      trainer.train_adversarial(
          student_generator,
          export_only=stats.get("adversarial") or kwargs["export_only"])
      if not kwargs["export_only"]:
        stats["adversarial"] = True
  # Tracing Graph to put input signature
  _ = student_generator.predict(
      tf.random.normal([1, 180, 320, 3]))
  tf.saved_model.save(
      student_generator,
      os.path.join(
          kwargs["modeldir"],
          "compressed_esrgan"))


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--tpu", default=None, help="Name of the TPU to use")
  parser.add_argument("--logdir", default=None, help="Path to log directory")
  parser.add_argument(
      "--export_only",
      default=False,
      action="store_true",
      help="Do not train, only export the model")
  parser.add_argument(
      "--config",
      default="config/config.yaml",
      help="path to config file")
  parser.add_argument(
      "--datadir",
      default=None,
      help="Path to custom data directory containing sharded TFRecords")
  parser.add_argument(
      "--modeldir",
      default=None,
      help="directory to store checkpoints and SavedModel")
  parser.add_argument(
      "--type",
      default=None,
      help="Train Student 'adversarial'-ly / 'comparative'-ly")
  parser.add_argument(
      "--verbose",
      "-v",
      default=0,
      action="count",
      help="Increases Verbosity. Repeat to increase more")

  FLAGS, unparsed = parser.parse_known_args()
  log_levels = [logging.FATAL, logging.WARNING, logging.INFO, logging.DEBUG]
  log_level = log_levels[min(FLAGS.verbose, len(log_levels) - 1)]
  logging.set_verbosity(log_level)
  train_and_export(**vars(FLAGS))
