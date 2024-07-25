import pandas as pd

from autorag.evaluator import Evaluator
from pathlib import Path

root = Path(__file__).parent.parent

compact_config_path = root / 'sample_config' / 'compact_openai.yaml'
dataset_name = "eli5"
qa_data_path = root / 'sample_dataset' / dataset_name / 'qa_train.parquet'
corpus_data_path = root / 'sample_dataset' / dataset_name / 'corpus.parquet'


class OptunaEvaluator:
    def evaluate(self):
        trial_root = Path(__file__).parent
        trial_folder = self.evaluate_config(config_path=trial_root / 'test_config.yaml')
        return self.get_metrics(trial_folder)

    def objective(self, trial):
        pass

    def get_last_trial_folder(self, trial_root: Path = Path(__file__).parent) -> Path:
        return trial_root / "0"

    def evaluate_config(self,
                        qa_path: Path = qa_data_path,
                        corpus_path: Path = corpus_data_path,
                        config_path: Path = compact_config_path
                        ) -> Path:
        evaluator = Evaluator(qa_data_path=str(qa_path), corpus_data_path=str(corpus_path))
        evaluator.start_trial(str(config_path))
        return self.get_last_trial_folder() / "retrieve_node_line" / "retrieval" / "summary.csv"

    def get_metrics(self, summary_path: Path):
        metrics = pd.DataFrame(pd.read_csv(str(summary_path))).iloc[0]
        return metrics


if __name__ == "__main__":
    optuna_evaluator = OptunaEvaluator()
    # print(optuna_evaluator.evaluate())
