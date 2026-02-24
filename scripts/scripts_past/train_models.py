from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

def _resolve_num_threads() -> int:
    configured = os.getenv("ALPHA_V4_NUM_THREADS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            pass
    detected = os.cpu_count() or 1
    return max(1, min(detected, 16))


NUM_THREADS = _resolve_num_threads()

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", str(NUM_THREADS))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(NUM_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(NUM_THREADS))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(NUM_THREADS))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score

from alpha_v4.config import (
    HYPERPARAMETERS,
    SYMBOLS,
    TEST_END,
    TIMEFRAMES,
    TRAIN_END,
    TRAIN_START,
    VALIDATION_END,
    all_model_feature_columns,
)
from alpha_v4.data_access import fetch_training_frame_all_symbols
from alpha_v4.db import get_connection
from alpha_v4.features import (
    cast_feature_matrix,
    engineer_features,
    inject_pairwise_correlations,
    normalize_training_dataframe,
)
from alpha_v4.model_registry import upsert_model_package
from alpha_v4.training_utils import purged_time_folds, split_by_dates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train alpha_v4 ensemble models.")
    parser.add_argument("--symbol", choices=SYMBOLS, help="Train only one symbol.")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, help="Train only one timeframe.")
    parser.add_argument("--version", default="v4.0.0", help="Model version string.")
    parser.add_argument("--train-start", default=TRAIN_START)
    parser.add_argument("--train-end", default=TRAIN_END)
    parser.add_argument("--validation-end", default=VALIDATION_END)
    parser.add_argument("--test-end", default=TEST_END)
    return parser.parse_args()


def compute_purged_cv_accuracy(frame: pd.DataFrame, timeframe: str) -> float:
    from xgboost import XGBClassifier

    folds = purged_time_folds(frame[["bucket_time"] + all_model_feature_columns(timeframe) + ["next_label_binary"]])
    scores = []
    for train_fold, test_fold in folds:
        if train_fold.empty or test_fold.empty:
            continue
        X_train = cast_feature_matrix(train_fold, timeframe)
        y_train = train_fold["next_label_binary"].astype(int)
        X_test = cast_feature_matrix(test_fold, timeframe)
        y_test = test_fold["next_label_binary"].astype(int)
        model = XGBClassifier(
            n_estimators=250,
            max_depth=3,
            learning_rate=0.03,
            subsample=0.7,
            colsample_bytree=0.7,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=NUM_THREADS,
        )
        model.fit(X_train.values, y_train.values, verbose=False)
        predicted = (model.predict_proba(X_test.values)[:, 1] >= 0.5).astype(int)
        scores.append(float(accuracy_score(y_test.values, predicted)))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def _prepare_symbol_dataset(
    frame_by_symbol: dict[str, pd.DataFrame],
    symbol: str,
) -> pd.DataFrame:
    frame = frame_by_symbol[symbol].copy()
    if frame.empty:
        return frame
    frame = frame.sort_values("bucket_time")
    inferred_labels = (frame["next_label"] == "UP").astype(int)
    frame["next_label_binary"] = frame["next_label_binary"].where(
        frame["next_label_binary"].notna(),
        inferred_labels,
    )
    frame = frame[frame["next_label_binary"].notna()].copy()
    frame["next_label_binary"] = frame["next_label_binary"].astype(int)
    return frame


def train_symbol_timeframe(
    connection,
    *,
    symbol: str,
    timeframe: str,
    version: str,
    train_start: str,
    train_end: str,
    validation_end: str,
    test_end: str,
) -> dict:
    from alpha_v4.modeling import (
        compute_metrics,
        ensemble_probabilities,
        model_feature_importance,
        serialize_package,
        train_calibrator,
        train_lightgbm,
        train_mlp,
        train_xgboost,
    )

    raw_all = fetch_training_frame_all_symbols(connection, timeframe, start_date=train_start, end_date=test_end)
    if raw_all.empty:
        raise RuntimeError(f"No training rows found for timeframe {timeframe}")
    raw_all = normalize_training_dataframe(raw_all)

    reference_all = None
    if timeframe == "15m":
        reference_all = fetch_training_frame_all_symbols(
            connection,
            "1h",
            start_date=train_start,
            end_date=test_end,
        )
        reference_all = normalize_training_dataframe(reference_all)

    features_by_symbol: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        sym_raw = raw_all[raw_all["symbol"] == sym].copy()
        if sym_raw.empty:
            features_by_symbol[sym] = pd.DataFrame()
            continue
        reference = None
        if timeframe == "15m" and reference_all is not None:
            reference = reference_all[reference_all["symbol"] == sym].copy()
        feature_frame = engineer_features(sym_raw, timeframe=timeframe, symbol=sym, reference_df=reference)
        merged = feature_frame.features.merge(
            sym_raw[["bucket_time", "next_label", "next_pct_change", "next_label_binary"]],
            on="bucket_time",
            how="left",
        )
        features_by_symbol[sym] = merged

    inject_pairwise_correlations(raw_all[["symbol", "bucket_time", "close"]], features_by_symbol)
    dataset = _prepare_symbol_dataset(features_by_symbol, symbol)
    if dataset.empty:
        raise RuntimeError(f"Empty dataset after feature engineering for {symbol} {timeframe}")

    splits = split_by_dates(
        dataset,
        train_start=train_start,
        train_end=train_end,
        valid_end=validation_end,
        test_end=test_end,
    )
    if splits.train.empty or splits.valid.empty or splits.test.empty:
        raise RuntimeError(f"Insufficient split rows for {symbol} {timeframe}")

    X_train = cast_feature_matrix(splits.train, timeframe)
    y_train = splits.train["next_label_binary"].astype(int)
    X_valid = cast_feature_matrix(splits.valid, timeframe)
    y_valid = splits.valid["next_label_binary"].astype(int)
    X_test = cast_feature_matrix(splits.test, timeframe)
    y_test = splits.test["next_label_binary"].astype(int)

    xgb_model = train_xgboost(X_train, y_train, X_valid, y_valid)
    lgb_model = train_lightgbm(X_train, y_train, X_valid, y_valid)
    mlp_bundle = train_mlp(X_train, y_train, X_valid, y_valid)

    valid_probs = ensemble_probabilities(xgb_model, lgb_model, mlp_bundle, X_valid)
    calibrator = train_calibrator(valid_probs["ensemble_raw_probability"], y_valid.values)

    calibrated_valid = ensemble_probabilities(
        xgb_model,
        lgb_model,
        mlp_bundle,
        X_valid,
        calibrator=calibrator,
    )
    calibrated_test = ensemble_probabilities(
        xgb_model,
        lgb_model,
        mlp_bundle,
        X_test,
        calibrator=calibrator,
    )

    val_metrics = compute_metrics(y_valid.values, calibrated_valid["ensemble_probability"])
    test_metrics = compute_metrics(y_test.values, calibrated_test["ensemble_probability"])
    cv_accuracy = compute_purged_cv_accuracy(splits.train, timeframe)

    feature_columns = list(X_train.columns)
    package = {
        "version": version,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_columns": feature_columns,
        "xgb_model": xgb_model,
        "lgb_model": lgb_model,
        "mlp_bundle": mlp_bundle,
        "calibrator": calibrator,
        "training_window": {
            "start": train_start,
            "train_end": train_end,
            "validation_end": validation_end,
            "test_end": test_end,
        },
        "metrics": {
            "validation": val_metrics.as_dict(),
            "test": test_metrics.as_dict(),
            "purged_cv_accuracy": cv_accuracy,
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    binary_package = serialize_package(package)

    feature_importance = model_feature_importance(feature_columns, xgb_model, lgb_model)
    hyperparameters = {
        "xgb": HYPERPARAMETERS.xgb,
        "lgb": HYPERPARAMETERS.lgb,
        "mlp": HYPERPARAMETERS.mlp,
    }
    metadata = {
        "test_metrics": test_metrics.as_dict(),
        "purged_cv_accuracy": cv_accuracy,
        "rows": {
            "train": int(len(X_train)),
            "valid": int(len(X_valid)),
            "test": int(len(X_test)),
        },
    }

    upsert_model_package(
        connection,
        model_name=f"{symbol}_{timeframe}_ensemble_{version}",
        symbol=symbol,
        timeframe=timeframe,
        version=version,
        train_start=train_start,
        train_end=train_end,
        train_samples=int(len(X_train)),
        val_metrics=val_metrics.as_dict(),
        feature_importance=feature_importance,
        hyperparameters=hyperparameters,
        model_binary=binary_package,
        feature_columns=feature_columns,
        metadata=metadata,
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "validation": val_metrics.as_dict(),
        "test": test_metrics.as_dict(),
        "purged_cv_accuracy": cv_accuracy,
        "train_rows": int(len(X_train)),
    }


def main() -> int:
    args = parse_args()
    symbols = [args.symbol] if args.symbol else list(SYMBOLS)
    timeframes = [args.timeframe] if args.timeframe else list(TIMEFRAMES)

    connection = get_connection(autocommit=False)
    try:
        summaries = []
        for timeframe in timeframes:
            for symbol in symbols:
                result = train_symbol_timeframe(
                    connection,
                    symbol=symbol,
                    timeframe=timeframe,
                    version=args.version,
                    train_start=args.train_start,
                    train_end=args.train_end,
                    validation_end=args.validation_end,
                    test_end=args.test_end,
                )
                summaries.append(result)
                print(
                    f"{symbol} {timeframe} "
                    f"val_acc={result['validation']['accuracy']:.4f} "
                    f"test_acc={result['test']['accuracy']:.4f}"
                )
        connection.commit()
        print(json.dumps({"models_trained": summaries}, indent=2))
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Training failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
