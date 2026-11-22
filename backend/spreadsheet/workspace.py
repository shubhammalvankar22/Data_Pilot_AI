
# Imports
from copy import deepcopy
from datetime import datetime, timezone

import pandas as pd


# Manage a working DataFrame with undo, redo and operation history
class DataWorkspace:
    """Manage a working DataFrame with undo, redo and operation history."""

    # Helper: init
    def __init__(self, dataframe):
        # Check condition
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("Expected a pandas DataFrame.")

        # Keep one original DataFrame reference; snapshots are created only on edits.
        self.original = dataframe.copy(deep=True)
        self.current = self.original
        self._states = [self.original]
        self._cursor = 0
        self.history = []

    # Function: can undo
    @property
    def can_undo(self):
        # Return result
        return self._cursor > 0

    # Function: can redo
    @property
    def can_redo(self):
        # Return result
        return self._cursor < len(self._states) - 1

    # Save a new DataFrame state and record the operation
    def _commit(self, updated, operation, details):
        """Save a new DataFrame state and record the operation."""
        # Check condition
        if not isinstance(updated, pd.DataFrame):
            raise TypeError("Operation must return a DataFrame.")

        # Set up values
        self._states = self._states[:self._cursor + 1]

        # Keep history aligned when a new edit replaces a redo branch.
        self.history = self.history[:self._cursor]

        # Store one snapshot per state and share it as the active DataFrame.
        snapshot = updated.copy(deep=True)
        self._states.append(snapshot)
        self._cursor += 1
        # Set up values
        self.current = snapshot

        self.history.append({
            "operation": operation,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Three states = current state plus at most two undo states.
        excess = max(0, len(self._states) - 3)
        # Check condition
        if excess:
            self._states = self._states[excess:]
            self._cursor -= excess
            self.history = self.history[excess:]

        # Return result
        return self.current.copy(deep=True)

    # Replace missing values in a selected column
    def replace_missing(self, column, replacement="Not Available"):
        """Replace missing values in a selected column."""
        # Check condition
        if column not in self.current.columns:
            raise ValueError(f"Column not found: {column}")

        # Set up values
        before = int(self.current[column].isna().sum())

        # Check condition
        if before == 0:
            return {"column": column, "cells_changed": 0}

        # Set up values
        updated = self.current.copy(deep=True)
        updated[column] = updated[column].astype(object)
        updated[column] = updated[column].where(
            updated[column].notna(), replacement
        )

        self._commit(
            updated,
            "replace_missing",
            {
                "column": column,
                "replacement": replacement,
                "cells_changed": before,
            },
        )

        # Return result
        return {"column": column, "cells_changed": before}

    # Impute missing numeric values and record the operation
    def impute_missing(
        self,
        column,
        method,
        constant=None,
        n_neighbors=5,
    ):
        """Impute missing numeric values and record the operation."""
        # Check condition
        if column not in self.current.columns:
            raise ValueError(f"Column not found: {column}")

        # Set up values
        numeric_columns = self.current.select_dtypes(
            include="number"
        ).columns.tolist()

        # Check condition
        if column not in numeric_columns:
            raise ValueError(
                "Select a numerical column for this operation."
            )

        # Set up values
        original_series = self.current[column]
        missing_mask = original_series.isna()
        before = int(missing_mask.sum())

        # Check condition
        if before == 0:
            return {
                "column": column,
                "method": method,
                "cells_changed": 0,
            }

        # Check condition
        if original_series.dropna().empty:
            raise ValueError(
                "This column has no observed values to learn from."
            )

        # Set up values
        updated = self.current.copy(deep=True)
        series = updated[column]

        # Check condition
        if method == "Mean":
            result = series.fillna(series.mean())

        elif method == "Median":
            result = series.fillna(series.median())

        elif method == "Mode":
            modes = series.mode()
            if modes.empty:
                raise ValueError("Cannot calculate mode.")
            result = series.fillna(modes.iloc[0])

        elif method == "Constant value":
            if constant is None:
                raise ValueError(
                    "Enter a numeric replacement value."
                )
            result = series.fillna(float(constant))

        elif method == "Forward fill":
            result = series.ffill()

        elif method == "Backward fill":
            result = series.bfill()

        elif method == "Linear interpolation":
            result = series.interpolate(method="linear")

        elif method in ("KNN Imputation", "Iterative Imputation"):
            from sklearn.experimental import (
                enable_iterative_imputer,  # noqa: F401
            )
            from sklearn.impute import KNNImputer, IterativeImputer

            features = self.current[numeric_columns].copy()
            features = features.loc[
                :, features.notna().any(axis=0)
            ]

            if column not in features.columns:
                raise ValueError(
                    "No usable numeric values exist in this column."
                )

            usable_rows = features.notna().any(axis=1)
            features = features.loc[usable_rows]

            if method == "KNN Imputation":
                imputer = KNNImputer(
                    n_neighbors=max(1, int(n_neighbors))
                )
            else:
                imputer = IterativeImputer(
                    max_iter=10,
                    random_state=42,
                )

            imputed_array = imputer.fit_transform(features)

            imputed_df = pd.DataFrame(
                imputed_array,
                index=features.index,
                columns=features.columns,
            )

            result = series.copy()
            rows_to_fill = (
                missing_mask
                & result.index.isin(imputed_df.index)
            )

            result.loc[rows_to_fill] = imputed_df.loc[
                result.index[rows_to_fill],
                column,
            ].to_numpy()

        else:
            raise ValueError(
                f"Unsupported imputation method: {method}"
            )

        # Set up values
        updated[column] = result

        cells_changed = int(
            (missing_mask & updated[column].notna()).sum()
        )

        # Check condition
        if cells_changed == 0:
            raise ValueError(
                "No missing values were filled. Check whether the "
                "selected method can fill the missing positions."
            )

        self._commit(
            updated,
            "impute_missing",
            {
                "column": column,
                "method": method,
                "cells_changed": cells_changed,
            },
        )

        # Return result
        return {
            "column": column,
            "method": method,
            "cells_changed": cells_changed,
        }

    # Add a calculated column and record it for undo/redo
    def create_column(self, column_name, values, description=""):
        """Add a calculated column and record it for undo/redo."""
        # Check condition
        if not isinstance(column_name, str) or not column_name.strip():
            raise ValueError("Enter a valid column name.")

        # Set up values
        column_name = column_name.strip()

        # Check condition
        if column_name in self.current.columns:
            raise ValueError(f"Column already exists: {column_name}")

        # Check condition
        if isinstance(values, pd.Series):
            # Require exact row alignment to avoid incorrect assignments.
            if not values.index.equals(self.current.index):
                raise ValueError(
                    "The calculated column's row index does not match "
                    "the current dataset."
                )
            new_values = values.copy(deep=True)
        else:
            try:
                new_values = pd.Series(
                    values,
                    index=self.current.index,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Calculated values must contain one value per row."
                ) from exc

        # Check condition
        if len(new_values) != len(self.current):
            raise ValueError(
                "The calculated column must contain one value per row."
            )

        # Set up values
        updated = self.current.copy(deep=True)
        updated[column_name] = new_values

        missing_results = int(updated[column_name].isna().sum())

        self._commit(
            updated,
            "create_column",
            {
                "column_name": column_name,
                "description": description,
                "rows_calculated": len(updated),
                "missing_results": missing_results,
            },
        )

        # Return result
        return {
            "column_name": column_name,
            "rows_calculated": len(updated),
            "missing_results": missing_results,
        }

    # Commit a same-shape or structurally changed DataFrame to history
    def replace_dataframe(self, dataframe, operation="replace_dataframe", details=None):
        """Commit a same-shape or structurally changed DataFrame to history."""
        # Check condition
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("Expected a pandas DataFrame.")
        # Check condition
        if dataframe.empty:
            raise ValueError("The working dataset cannot be empty.")
        # Check condition
        if dataframe.columns.duplicated().any():
            raise ValueError("Column names must be unique.")
        self._commit(dataframe, operation, details or {})
        # Return result
        return self.current.copy(deep=True)

    # Convert a Series to one of the spreadsheet ribbon data types
    @staticmethod
    def _convert_series(series, target_type):
        """Convert a Series to one of the spreadsheet ribbon data types."""
        target = str(target_type).strip().lower()
        # Check condition
        if target == "text":
            return series.astype("string")
        # Check condition
        if target == "whole number":
            numeric = pd.to_numeric(series, errors="raise")
            non_null = numeric.dropna()
            if not non_null.empty and ((non_null % 1) != 0).any():
                raise ValueError("Some values contain decimal parts and cannot be converted to whole numbers without data loss.")
            return numeric.astype("Int64")
        # Check condition
        if target == "decimal number":
            return pd.to_numeric(series, errors="raise").astype(float)
        # Check condition
        if target == "percentage":
            # Parse percent
            def parse_percent(value):
                # Check condition
                if pd.isna(value):
                    return float("nan")
                # Check condition
                if isinstance(value, str) and value.strip().endswith("%"):
                    return float(value.strip()[:-1].replace(",", "")) / 100.0
                # Return result
                return float(value)
            return series.map(parse_percent).astype(float)
        # Check condition
        if target == "date":
            converted = pd.to_datetime(series, errors="raise")
            return converted.dt.normalize()
        # Check condition
        if target == "date/time":
            return pd.to_datetime(series, errors="raise")
        # Check condition
        if target == "true/false":
            mapping = {
                "true": True, "false": False,
                "yes": True, "no": False,
                "1": True, "0": False,
                "y": True, "n": False,
            }
            # Parse bool
            def parse_bool(value):
                # Check condition
                if pd.isna(value):
                    return pd.NA
                # Check condition
                if isinstance(value, bool):
                    return value
                # Set up values
                text = str(value).strip().lower()
                # Check condition
                if text not in mapping:
                    raise ValueError(f"Cannot interpret {value!r} as True/False.")
                # Return result
                return mapping[text]
            return series.map(parse_bool).astype("boolean")
        raise ValueError(f"Unsupported target data type: {target_type}")

    # Validate a proposed column type conversion without changing data
    def preview_column_type(self, column_name, target_type):
        """Validate a proposed column type conversion without changing data."""
        # Check condition
        if column_name not in self.current.columns:
            raise ValueError(f"Column not found: {column_name}")
        # Set up values
        source = self.current[column_name]
        # Try, handle errors
        try:
            converted = self._convert_series(source, target_type)
            return {"converted": converted, "bad_values": []}
        except Exception:
            # Identify failing values one by one so the UI can show examples.
            bad_values = []
            for index, value in source.items():
                if pd.isna(value):
                    continue
                try:
                    self._convert_series(pd.Series([value]), target_type)
                except Exception:
                    bad_values.append((index, value))
            return {"converted": None, "bad_values": bad_values or [("—", "Conversion failed; check source values and target type.")]}

    # Convert a column type and save the conversion to undo/redo history
    def convert_column_type(self, column_name, target_type):
        """Convert a column type and save the conversion to undo/redo history."""
        preview = self.preview_column_type(column_name, target_type)
        # Check condition
        if preview["bad_values"]:
            examples = preview["bad_values"][:5]
            raise ValueError(f"Conversion contains invalid values, for example: {examples}")
        # Set up values
        updated = self.current.copy(deep=True)
        updated[column_name] = preview["converted"]
        self._commit(updated, "convert_column_type", {"column": column_name, "target_type": target_type})
        # Return result
        return {"column": column_name, "target_type": target_type}

    # Sort rows by a column and record the operation
    def sort_values(self, column_name, ascending=True):
        """Sort rows by a column and record the operation."""
        # Check condition
        if column_name not in self.current.columns:
            raise ValueError(f"Column not found: {column_name}")
        # Set up values
        updated = self.current.sort_values(column_name, ascending=ascending, na_position="last", kind="stable").reset_index(drop=True)
        self._commit(updated, "sort_values", {"column": column_name, "ascending": bool(ascending)})
        # Return result
        return {"column": column_name, "ascending": bool(ascending)}

    # Remove a column and record it for undo/redo
    def remove_column(self, column_name):
        """Remove a column and record it for undo/redo."""
        # Check condition
        if column_name not in self.current.columns:
            raise ValueError(f"Column not found: {column_name}")
        # Check condition
        if len(self.current.columns) <= 1:
            raise ValueError("At least one column must remain.")
        # Set up values
        updated = self.current.drop(columns=[column_name]).copy(deep=True)
        self._commit(updated, "remove_column", {"column_name": column_name})
        # Return result
        return {"column_name": column_name, "columns_remaining": len(updated.columns)}

    # Rename a column and record the operation
    def rename_column(self, old_name, new_name):
        """Rename a column and record the operation."""
        # Check condition
        if old_name not in self.current.columns:
            raise ValueError(f"Column not found: {old_name}")

        # Check condition
        if not isinstance(new_name, str) or not new_name.strip():
            raise ValueError("New column name cannot be empty.")

        # Set up values
        new_name = new_name.strip()

        # Check condition
        if new_name in self.current.columns:
            raise ValueError(
                "New column name already exists."
            )

        # Set up values
        updated = self.current.rename(
            columns={old_name: new_name}
        )

        self._commit(
            updated,
            "rename_column",
            {"old_name": old_name, "new_name": new_name},
        )

        # Return result
        return {"old_name": old_name, "new_name": new_name}

    # Remove duplicate rows and record the operation
    def remove_duplicates(self):
        """Remove duplicate rows and record the operation."""
        before = len(self.current)
        updated = self.current.drop_duplicates().copy()
        removed = before - len(updated)

        # Check condition
        if removed == 0:
            return {"rows_removed": 0}

        self._commit(
            updated,
            "remove_duplicates",
            {"rows_removed": removed},
        )

        # Return result
        return {"rows_removed": removed}

    # Restore the previous workspace state
    def undo(self):
        """Restore the previous workspace state."""
        # Check condition
        if not self.can_undo:
            return {
                "success": False,
                "message": "Nothing to undo.",
            }

        self._cursor -= 1
        # Set up values
        self.current = self._states[self._cursor]

        # Return result
        return {
            "success": True,
            "data": self.current.copy(deep=True),
        }

    # Restore the next workspace state
    def redo(self):
        """Restore the next workspace state."""
        # Check condition
        if not self.can_redo:
            return {
                "success": False,
                "message": "Nothing to redo.",
            }

        self._cursor += 1
        # Set up values
        self.current = self._states[self._cursor]

        # Return result
        return {
            "success": True,
            "data": self.current.copy(deep=True),
        }

    # Restore the original uploaded dataset and clear history
    def reset(self):
        """Restore the original uploaded dataset and clear history."""
        self.current = self.original
        self._states = [self.original]
        self._cursor = 0
        self.history = []

        # Return result
        return self.current.copy(deep=True)

    # Return a copy of the operation history
    def get_history(self):
        """Return a copy of the operation history."""
        # Return result
        return deepcopy(self.history)

    # Return the current dataset as a downloadable CSV byte string
    def download_csv(self):
        """Return the current dataset as a downloadable CSV byte string."""
        # Return result
        return self.current.to_csv(index=False).encode("utf-8-sig")
