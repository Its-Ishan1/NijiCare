"""Score the bundled model artifacts on the saved validation splits without fitting."""
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from ml_models import ColumnValueClassifier, LinearChainCRF, crf_token_features, extract_column_features


class ModelReader(pickle.Unpickler):
    """Only resolve the classes and NumPy helpers used by the supplied artifacts."""
    allowed = {
        "sklearn.feature_extraction._dict_vectorizer.DictVectorizer",
        "sklearn.svm._classes.LinearSVC", "sklearn.linear_model._logistic.LogisticRegression",
        "sklearn.ensemble._forest.RandomForestClassifier", "sklearn.tree._classes.DecisionTreeClassifier",
        "sklearn.tree._tree.Tree", "sklearn.neural_network._multilayer_perceptron.MLPClassifier",
        "sklearn.neural_network._stochastic_optimizers.AdamOptimizer", "sklearn.preprocessing._label.LabelBinarizer",
        "numpy.float64", "numpy.dtype", "numpy.ndarray", "numpy._core.numeric._frombuffer",
        "numpy._core.multiarray._reconstruct", "numpy._core.multiarray.scalar",
        "numpy.random._pickle.__randomstate_ctor", "numpy.random._pickle.__bit_generator_ctor",
        "numpy.random._mt19937.MT19937",
    }

    def find_class(self, module, name):
        if f"{module}.{name}" not in self.allowed:
            raise pickle.UnpicklingError(f"Unexpected model dependency: {module}.{name}")
        return super().find_class(module, name)


def read_split(name):
    with (ROOT / "generated_datasets" / f"{name}_val.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def ner_score(notes, predicted):
    tp = fp = fn = neg = neg_fp = 0
    for item, pred in zip(notes, predicted, strict=True):
        gold = item["tags"]
        if all(tag == "O" for tag in gold):
            neg += 1
            neg_fp += any(tag != "O" for tag in pred)
        for expected, actual in zip(gold, pred, strict=True):
            tp += actual != "O" and actual == expected
            fp += actual != "O" and actual != expected
            fn += expected != "O" and actual != expected
    return dict(tp=tp, fp=fp, fn=fn, precision=tp/(tp+fp), recall=tp/(tp+fn),
                token_f1=2*tp/(2*tp+fp+fn), negative_notes=neg, false_positive_notes=neg_fp)


def column_score(gold, predicted):
    wrong = Counter(f"{a} -> {b}" for a, b in zip(gold, predicted, strict=True) if a != b)
    return dict(correct=len(gold)-sum(wrong.values()), total=len(gold),
                macro_f1=float(f1_score(gold, predicted, average="macro")), errors=dict(wrong))


def check_models():
    notes, columns = read_split("ner"), read_split("col")
    models = ROOT.parent / "models"
    crf = LinearChainCRF.load(models / "ner_crf.json.gz")
    predicted = []
    for item in notes:
        labels, confidence = crf.predict_with_marginals(item["tokens"])
        predicted.append([tag if p >= 0.85 else "O" for tag, p in zip(labels, confidence, strict=True)])
    results = {"deployed_crf": ner_score(notes, predicted)}

    clf = ColumnValueClassifier.load(models / "col_clf.json.gz")
    gold = [item["label"] for item in columns]
    scores = [clf.predict_proba(item["values"]) for item in columns]
    results["deployed_column"] = column_score(gold, [max(p, key=p.get) for p in scores])
    expected_pii = [s if s not in ("CLINICAL", "OTHER") else None for s in gold]
    guarded = [clf.classify_column(item["values"], threshold=0.80) for item in columns]
    results["column_with_runtime_guards"] = dict(
        pii_columns=sum(s is not None for s in expected_pii),
        correct_pii=sum(s is not None and s == p for s, p in zip(expected_pii, guarded)),
        false_positives=sum(s is None and p is not None for s, p in zip(expected_pii, guarded)),
        missed=dict(Counter(s for s, p in zip(expected_pii, guarded) if s is not None and s != p)))

    token_features = [dict.fromkeys(crf_token_features(n["tokens"], i), 1.0)
                      for n in notes for i in range(len(n["tokens"]))]
    column_features = [extract_column_features(c["values"]) for c in columns]
    for path in sorted((ROOT / "artifacts").glob("*.pkl")):
        with path.open("rb") as stream:
            bundle = ModelReader(stream).load()
        model, vectorizer = bundle["model"], bundle["vectorizer"]
        if path.stem.startswith("sklearn_col_"):
            pred = model.predict(vectorizer.transform(column_features))
            results[path.stem] = column_score(gold, pred)
        else:
            x = vectorizer.transform(token_features)
            flat = model.predict(x)
            if hasattr(model, "predict_proba"):
                flat = [tag if p >= 0.85 else "O" for tag, p in zip(flat, model.predict_proba(x).max(axis=1))]
            tags = iter(flat)
            seq = [[next(tags) for _ in note["tokens"]] for note in notes]
            results[path.stem] = ner_score(notes, seq)
    return results


if __name__ == "__main__":
    print(json.dumps(check_models(), indent=2))
