from autorag.evaluator import Evaluator


def main():
    evaluator = Evaluator(qa_data_path='datasets/qa_test.parquet', corpus_data_path='datasets/corpus.parquet')
    evaluator.start_trial('sample_config/compact_openai.yaml')


if __name__ == "__main__":
    main()
