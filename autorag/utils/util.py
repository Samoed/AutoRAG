import ast
import asyncio
import datetime
import functools
import glob
import itertools
import logging
import os
import re
import string
from copy import deepcopy
from typing import List, Callable, Dict, Optional, Any, Collection, Iterable

import numpy as np
import pandas as pd
import tiktoken
import unicodedata
from llama_index.embeddings.openai import OpenAIEmbedding
from pydantic import BaseModel as BM
from pydantic.v1 import BaseModel
from tqdm import tqdm

logger = logging.getLogger("AutoRAG")


def fetch_contents(corpus_data: pd.DataFrame, ids: List[List[str]],
                   column_name: str = 'contents') -> List[List[Any]]:
    def fetch_contents_pure(ids: List[str], corpus_data: pd.DataFrame, column_name: str):
        return list(map(lambda x: fetch_one_content(corpus_data, x, column_name), ids))

    result = flatten_apply(fetch_contents_pure, ids, corpus_data=corpus_data, column_name=column_name)
    return result


def fetch_one_content(corpus_data: pd.DataFrame, id_: str,
                      column_name: str = 'contents') -> Any:
    if isinstance(id_, str):
        if id_ in ['', ""]:
            return None
        fetch_result = corpus_data[corpus_data['doc_id'] == id_]
        if fetch_result.empty:
            raise ValueError(f"doc_id: {id_} not found in corpus_data.")
        else:
            return fetch_result[column_name].iloc[0]
    else:
        return None


def result_to_dataframe(column_names: List[str]):
    """
    Decorator for converting results to pd.DataFrame.
    """

    def decorator_result_to_dataframe(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> pd.DataFrame:
            results = func(*args, **kwargs)
            if len(column_names) == 1:
                df_input = {column_names[0]: results}
            else:
                df_input = {column_name: result for result, column_name in zip(results, column_names)}
            result_df = pd.DataFrame(df_input)
            return result_df

        return wrapper

    return decorator_result_to_dataframe


def load_summary_file(summary_path: str,
                      dict_columns: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Load summary file from summary_path.

    :param summary_path: The path of the summary file.
    :param dict_columns: The columns that are dictionary type.
        You must fill this parameter if you want to load summary file properly.
        Default is ['module_params'].
    :return: The summary dataframe.
    """
    if not os.path.exists(summary_path):
        raise ValueError(f"summary.csv does not exist in {summary_path}.")
    summary_df = pd.read_csv(summary_path)
    if dict_columns is None:
        dict_columns = ['module_params']

    if any([col not in summary_df.columns for col in dict_columns]):
        raise ValueError(f"{dict_columns} must be in summary_df.columns.")

    def convert_dict(elem):
        try:
            return ast.literal_eval(elem)
        except:
            # convert datetime or date to its object (recency filter)
            date_object = convert_datetime_string(elem)
            if date_object is None:
                raise ValueError(f"Malformed dict received : {elem}\nCan't convert to dict properly")
            return {'threshold': date_object}

    summary_df[dict_columns] = summary_df[dict_columns].applymap(convert_dict)
    return summary_df


def convert_datetime_string(s):
    # Regex to extract datetime arguments from the string
    m = re.search(r"(datetime|date)(\((\d+)(,\s*\d+)*\))", s)
    if m:
        args = ast.literal_eval(m.group(2))
        if m.group(1) == 'datetime':
            return datetime.datetime(*args)
        elif m.group(1) == 'date':
            return datetime.date(*args)
    return None


def make_combinations(target_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Make combinations from target_dict.
    The target_dict key value must be a string,
    and the value can be list of values or single value.
    If generates all combinations of values from target_dict,
    which means generated dictionaries that contain only one value for each key,
    and all dictionaries will be different from each other.

    :param target_dict: The target dictionary.
    :return: The list of generated dictionaries.
    """
    dict_with_lists = dict(map(lambda x: (x[0], x[1] if isinstance(x[1], list) else [x[1]]),
                               target_dict.items()))

    def delete_duplicate(x):
        def is_hashable(obj):
            try:
                hash(obj)
                return True
            except TypeError:
                return False

        if any([not is_hashable(elem) for elem in x]):
            # TODO: add duplication check for unhashable objects
            return x
        else:
            return list(set(x))

    dict_with_lists = dict(map(lambda x: (x[0], delete_duplicate(x[1])), dict_with_lists.items()))
    combination = list(itertools.product(*dict_with_lists.values()))
    combination_dicts = [dict(zip(dict_with_lists.keys(), combo)) for combo in combination]
    return combination_dicts


def explode(index_values: Collection[Any], explode_values: Collection[Collection[Any]]):
    """
    Explode index_values and explode_values.
    The index_values and explode_values must have the same length.
    It will flatten explode_values and keep index_values as a pair.

    :param index_values: The index values.
    :param explode_values: The exploded values.
    :return: Tuple of exploded index_values and exploded explode_values.
    """
    assert len(index_values) == len(explode_values), "Index values and explode values must have same length"
    df = pd.DataFrame({
        'index_values': index_values,
        'explode_values': explode_values
    })
    df = df.explode('explode_values')
    return df['index_values'].tolist(), df['explode_values'].tolist()


def replace_value_in_dict(target_dict: Dict, key: str,
                          replace_value: Any) -> Dict:
    """
    Replace the value of the certain key in target_dict.
    If there is not targeted key in target_dict, it will return target_dict.

    :param target_dict: The target dictionary.
    :param key: The key to replace.
    :param replace_value: The value to replace.
    :return: The replaced dictionary.
    """
    replaced_dict = deepcopy(target_dict)
    if key not in replaced_dict:
        return replaced_dict
    replaced_dict[key] = replace_value
    return replaced_dict


def normalize_string(s: str) -> str:
    """
    Taken from the official evaluation script for v1.1 of the SQuAD dataset.
    Lower text and remove punctuation, articles and extra whitespace.
    """

    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text):
        return " ".join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    return white_space_fix(remove_articles(remove_punc(lower(s))))


def convert_string_to_tuple_in_dict(d):
    """Recursively converts strings that start with '(' and end with ')' to tuples in a dictionary."""
    for key, value in d.items():
        # If the value is a dictionary, recurse
        if isinstance(value, dict):
            convert_string_to_tuple_in_dict(value)
        # If the value is a list, iterate through its elements
        elif isinstance(value, list):
            for i, item in enumerate(value):
                # If an item in the list is a dictionary, recurse
                if isinstance(item, dict):
                    convert_string_to_tuple_in_dict(item)
                # If an item in the list is a string matching the criteria, convert it to a tuple
                elif isinstance(item, str) and item.startswith('(') and item.endswith(')'):
                    value[i] = ast.literal_eval(item)
        # If the value is a string matching the criteria, convert it to a tuple
        elif isinstance(value, str) and value.startswith('(') and value.endswith(')'):
            d[key] = ast.literal_eval(value)

    return d


def convert_env_in_dict(d: Dict):
    """
    Recursively converts environment variable string in a dictionary to actual environment variable.

    :param d: The dictionary to convert.
    :return: The converted dictionary.
    """
    env_pattern = re.compile(r".*?\${(.*?)}.*?")

    def convert_env(val: str):
        matches = env_pattern.findall(val)
        for match in matches:
            val = val.replace(f"${{{match}}}", os.environ.get(match, ""))
        return val

    for key, value in d.items():
        if isinstance(value, dict):
            convert_env_in_dict(value)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    convert_env_in_dict(item)
                elif isinstance(item, str):
                    value[i] = convert_env(item)
        elif isinstance(value, str):
            d[key] = convert_env(value)
    return d


async def process_batch(tasks, batch_size: int = 64) -> List[Any]:
    """
    Processes tasks in batches asynchronously.

    :param tasks: A list of no-argument functions or coroutines to be executed.
    :param batch_size: The number of tasks to process in a single batch.
        Default is 64.
    :return: A list of results from the processed tasks.
    """
    results = []

    for i in tqdm(range(0, len(tasks), batch_size)):
        batch = tasks[i:i + batch_size]
        batch_results = await asyncio.gather(*batch)
        results.extend(batch_results)

    return results


def make_batch(elems: List[Any], batch_size: int) -> List[List[Any]]:
    """
    Make a batch of elems with batch_size.
    """
    return [elems[i:i + batch_size] for i in range(0, len(elems), batch_size)]


def save_parquet_safe(df: pd.DataFrame, filepath: str,
                      upsert: bool = False):
    output_file_dir = os.path.dirname(filepath)
    if not os.path.isdir(output_file_dir):
        raise NotADirectoryError(f"directory {output_file_dir} not found.")
    if not filepath.endswith("parquet"):
        raise NameError(f'file path: {filepath}  filename extension need to be ".parquet"')
    if os.path.exists(filepath) and not upsert:
        raise FileExistsError(f"file {filepath} already exists."
                              "Set upsert True if you want to overwrite the file.")

    df.to_parquet(filepath, index=False)


def openai_truncate_by_token(texts: List[str], token_limit: int,
                             model_name: str) -> List[str]:
    tokenizer = tiktoken.encoding_for_model(model_name)

    def truncate_text(text: str, limit: int, tokenizer):
        tokens = tokenizer.encode(text)
        if len(tokens) <= limit:
            return text
        truncated_text = tokenizer.decode(tokens[:limit])
        return truncated_text

    return list(map(lambda x: truncate_text(x, token_limit, tokenizer), texts))


def reconstruct_list(flat_list: List[Any], lengths: List[int]) -> List[List[Any]]:
    result = []
    start = 0
    for length in lengths:
        result.append(flat_list[start:start + length])
        start += length
    return result


def flatten_apply(func: Callable, nested_list: List[List[Any]], **kwargs) -> List[List[Any]]:
    """
    This function flattens the input list and applies the function to the elements.
    After that, it reconstructs the list to the original shape.
    Its speciality is that the first dimension length of the list can be different from each other.

    :param func: The function that applies to the flattened list.
    :param nested_list: The nested list to be flattened.
    :return: The list that is reconstructed after applying the function.
    """
    df = pd.DataFrame({'col1': nested_list})
    df = df.explode('col1')
    df['result'] = func(df['col1'].tolist(), **kwargs)
    return df.groupby(level=0, sort=False)['result'].apply(list).tolist()


def sort_by_scores(row, reverse=True):
    """
    Sorts each row by 'scores' column.
    The input column names must be 'contents', 'ids', and 'scores'.
    And its elements must be list type.
    """
    results = sorted(zip(row['contents'], row['ids'], row['scores']), key=lambda x: x[2], reverse=reverse)
    reranked_contents, reranked_ids, reranked_scores = zip(*results)
    return list(reranked_contents), list(reranked_ids), list(reranked_scores)


def select_top_k(df, column_names: List[str], top_k: int):
    for column_name in column_names:
        df[column_name] = df[column_name].apply(lambda x: x[:top_k])
    return df


def filter_dict_keys(dict_, keys: List[str]):
    result = {}
    for key in keys:
        if key in dict_:
            result[key] = dict_[key]
        else:
            raise KeyError(f"Key '{key}' not found in dictionary.")
    return result


def split_dataframe(df, chunk_size):
    num_chunks = len(df) // chunk_size + 1 if len(df) % chunk_size != 0 else len(df) // chunk_size
    result = list(map(lambda x: df[x * chunk_size:(x + 1) * chunk_size], range(num_chunks)))
    result = list(map(lambda x: x.reset_index(drop=True), result))
    return result


def find_trial_dir(project_dir: str) -> List[str]:
    # Pattern to match directories named with numbers
    pattern = os.path.join(project_dir, '[0-9]*')
    all_entries = glob.glob(pattern)

    # Filter out only directories
    trial_dirs = [entry for entry in all_entries if os.path.isdir(entry) and entry.split(os.sep)[-1].isdigit()]

    return trial_dirs


def find_node_summary_files(trial_dir: str) -> List[str]:
    # Find all summary.csv files recursively
    all_summary_files = glob.glob(os.path.join(trial_dir, '**', 'summary.csv'), recursive=True)

    # Filter out files that are at a lower directory level
    filtered_files = [f for f in all_summary_files if f.count(os.sep) > trial_dir.count(os.sep) + 2]

    return filtered_files


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize('NFC', text)


def dict_to_markdown(d, level=1):
    """
    Convert a dictionary to a Markdown formatted string.

    :param d: Dictionary to convert
    :param level: Current level of heading (used for nested dictionaries)
    :return: Markdown formatted string
    """
    markdown = ""
    for key, value in d.items():
        if isinstance(value, dict):
            markdown += f"{'#' * level} {key}\n"
            markdown += dict_to_markdown(value, level + 1)
        elif isinstance(value, list):
            markdown += f"{'#' * level} {key}\n"
            for item in value:
                if isinstance(item, dict):
                    markdown += dict_to_markdown(item, level + 1)
                else:
                    markdown += f"- {item}\n"
        else:
            markdown += f"{'#' * level} {key}\n{value}\n"
    return markdown


def dict_to_markdown_table(data, key_column_name: str, value_column_name: str):
    # Check if the input is a dictionary
    if not isinstance(data, dict):
        raise ValueError("Input must be a dictionary")

    # Create the header of the table
    header = f"| {key_column_name} | {value_column_name} |\n| :---: | :-----: |\n"

    # Create the rows of the table
    rows = ""
    for key, value in data.items():
        rows += f"| {key} | {value} |\n"

    # Combine header and rows
    markdown_table = header + rows
    return markdown_table


def embedding_query_content(queries: List[str], contents_list: List[List[str]],
                            embedding_model: Optional[str] = None, batch: int = 128):
    flatten_contents = list(itertools.chain.from_iterable(contents_list))

    openai_embedding_limit = 8191  # all openai embedding model has 8191 max token input
    if isinstance(embedding_model, OpenAIEmbedding):
        queries = openai_truncate_by_token(queries, openai_embedding_limit,
                                           embedding_model.model_name)
        flatten_contents = openai_truncate_by_token(flatten_contents, openai_embedding_limit,
                                                    embedding_model.model_name)

    # Embedding using batch
    embedding_model.embed_batch_size = batch
    query_embeddings = embedding_model.get_text_embedding_batch(queries)

    content_lengths = list(map(len, contents_list))
    content_embeddings_flatten = embedding_model.get_text_embedding_batch(flatten_contents)
    content_embeddings = reconstruct_list(content_embeddings_flatten, content_lengths)
    return query_embeddings, content_embeddings


def to_list(item):
    """Recursively convert collections to Python lists."""
    if isinstance(item, np.ndarray):
        # Convert numpy array to list and recursively process each element
        return [to_list(sub_item) for sub_item in item.tolist()]
    elif isinstance(item, pd.Series):
        # Convert pandas Series to list and recursively process each element
        return [to_list(sub_item) for sub_item in item.tolist()]
    elif isinstance(item, Iterable) and not isinstance(item, (str, bytes, BaseModel, BM)):
        # Recursively process each element in other iterables
        return [to_list(sub_item) for sub_item in item]
    else:
        return item


def convert_inputs_to_list(func):
    """Decorator to convert all function inputs to Python lists."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        new_args = [to_list(arg) for arg in args]
        new_kwargs = {k: to_list(v) for k, v in kwargs.items()}
        return func(*new_args, **new_kwargs)

    return wrapper
