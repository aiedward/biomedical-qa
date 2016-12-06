import os
import sys
import json
import logging
import re
import numpy as np
from nltk import RegexpTokenizer

TRAIN_FRACTION = 0.8
# Max is ~4300, SQuAD max is ~700
CONTEXT_TOKEN_LIMIT = 700

TOKENIZER = RegexpTokenizer(r'\w+|[^\w\s]')

np.random.seed(1234)


def convert_to_squad(bioasq_file_path, out_dir):

  with open(bioasq_file_path) as json_file:
    data = json.load(json_file)

  paragraphs, contexts_truncated = build_paragraphs(data)
  train_paragraphs, dev_paragraphs = split_paragraphs(paragraphs)

  os.makedirs(out_dir, exist_ok=True)

  with open(os.path.join(out_dir, "train.json"), "w") as out_file:
    name = bioasq_file_path + " - train"
    result = build_result_object(name, train_paragraphs)
    json.dump(result, out_file, indent=2)

  with open(os.path.join(out_dir, "dev.json"), "w") as out_file:
    name = bioasq_file_path + " - dev"
    result = build_result_object(name, dev_paragraphs)
    json.dump(result, out_file, indent=2)

  print("Done. Extracted %d questions (%d train & %d dev)"
        % (len(paragraphs), len(train_paragraphs), len(dev_paragraphs)))

  num_factoid_original = len([q for q in data["questions"] if q["type"] == "factoid"])
  num_list_original = len([q for q in data["questions"] if q["type"] == "list"])
  num_factoid = len([p for p in paragraphs
                     if p["qas"][0]["question_type"] == "factoid"])
  num_list = len([p for p in paragraphs
                  if p["qas"][0]["question_type"] == "list"])
  max_context_len = max([len(TOKENIZER.tokenize(p["context"]))
                         for p in paragraphs])

  print("Max Context Length: %d tokens" % max_context_len)
  print("Contexts truncated: %d" % contexts_truncated)
  print("Used Factoid questions: %d / %d" % (num_factoid, num_factoid_original))
  print("Used List questions: %d / %d" % (num_list, num_list_original))


def split_paragraphs(paragraphs):

  dataset_size = len(paragraphs)
  train_size = int(TRAIN_FRACTION * dataset_size)

  train_indices = np.random.choice(dataset_size, train_size, replace=False)

  train_paragraphs, dev_paragraphs = [], []
  for i in np.random.permutation(dataset_size):
    if i in train_indices:
      train_paragraphs += [paragraphs[i]]
    else:
      dev_paragraphs += [paragraphs[i]]

  return train_paragraphs, dev_paragraphs


def build_result_object(name, paragraphs):

  return {
    "version": "1.0",
    "data": [
      {
        "title": name,
        "paragraphs": paragraphs
      }
    ]
  }


def build_paragraphs(data):

  paragraphs = [build_paragraph(question)
                for question in filter_questions(data["questions"])]
  paragraphs = [p for p in paragraphs if p is not None]

  paragraphs, context_truncated = zip(*paragraphs)

  return paragraphs, sum(context_truncated)


def filter_questions(questions):

  result = []

  for question in questions:

    if not question["type"] in ["factoid", "list"]:
      continue

    if len(question["snippets"]) == 0:
      logging.warning("Skipping question %s. No snippets." % question["id"])
      continue

    result.append(question)

  return result


def build_paragraph(question):

  context, context_truncated = get_context(question)
  answers = get_answers(question, context)

  if answers is None:
    return None

  paragraph = {
    "context": context.lower(),
    "qas": [
      {
        "id": question["id"],
        "question": question["body"].lower(),
        "answers": answers,
        "original_answers": question["exact_answer"],
        "question_type": question["type"]
      }
    ]
  }

  return paragraph, context_truncated


def get_context(question):

  num_tokens = 0
  snippets_set = set()
  snippets = [snippet["text"] for snippet in question["snippets"]]
  filtered_tickets = []

  did_truncate = False

  for snippet in snippets:

    # Deduplicate Snippets
    if snippet in snippets_set:
      continue
    snippets_set.add(snippet)

    # Keep token limit
    num_tokens += len(TOKENIZER.tokenize(snippet))
    if num_tokens > CONTEXT_TOKEN_LIMIT:
      did_truncate = True
      break

    filtered_tickets.append(snippet)

  return " ".join(filtered_tickets), did_truncate


def get_answers(question, context):

  context = context.lower()

  def find_best_answer(answers):

    for answer in answers:
      if answer.lower() in context and len(answer):
        return answer

    return answers[0]

  answers = [a if isinstance(a, str) else find_best_answer(a)
             for a in question["exact_answer"]]

  assert len(answers)

  answer_objects = []

  for answer in answers:

    answer = clean_answer(answer)

    for start_position in find_all_substring_positions(context, answer):
      answer_objects += [
        {
          "answer_start": start_position,
          "text": answer
        }
      ]

  if not len(answer_objects):
    # Skip question
    logging.warning("Skipping question %s. No matching answer." %
                    question["id"])
    # print("  Skipping question %s. No matching answer." %
    #                 question["id"])
    # print("  Q:", question["body"])
    # print("  C:", context)
    # print("  A:", answers)
    # sys.stdout.flush()
    return None

  return answer_objects


def clean_answer(answer):

  answer = answer.strip().lower()
  if answer.startswith("the "):
    answer = answer[4:]
  if re.search(r"[^\w]$", answer) is not None:
    # Ends with punctuation
    answer = answer[:-1]

  return answer


def find_all_substring_positions(string, substring):

  if not len(substring):
    return []

  search_strings = ["\\W%s\\W" % re.escape(substring),
                    "^%s\\W" % re.escape(substring),
                    "\\W%s$" % re.escape(substring)]
  return [m.start() + 1
          for search_string in search_strings
          for m in re.finditer(search_string, string)]


if __name__ == "__main__":

  if len(sys.argv) < 3:

    print("Usage: %s <BioASQ json file> <out dir>" % sys.argv[0])
    exit(1)

  _, bioasq_file_path, out_dir = sys.argv
  convert_to_squad(bioasq_file_path, out_dir)
