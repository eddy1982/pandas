"""
Data structures for sparse float data. Life is made simpler by dealing only
with float64 data
"""

# pylint: disable=E1101,E1103,W0231

from numpy import nan, ndarray
import numpy as np

import operator

from pandas.core.common import isnull, _values_from_object, _maybe_match_name
from pandas.core.index import Index, _ensure_index
from pandas.core.series import Series
from pandas.core.frame import DataFrame
from pandas.core.internals import SingleBlockManager
from pandas.core import generic
import pandas.core.common as com
import pandas.core.ops as ops
import pandas.core.datetools as datetools
import pandas.index as _index

from pandas import compat

from pandas.sparse.array import (make_sparse, _sparse_array_op, SparseArray)
from pandas._sparse import BlockIndex, IntIndex
import pandas._sparse as splib

from pandas.util.decorators import Appender

#------------------------------------------------------------------------------
# Wrapper function for Series arithmetic methods


def _arith_method(op, name, str_rep=None, default_axis=None, fill_zeros=None,
                                 **eval_kwargs):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.

    str_rep, default_axis, fill_zeros and eval_kwargs are not used, but are present
    for compatibility.
    """

    def wrapper(self, other):
        if isinstance(other, Series):
            if not isinstance(other, SparseSeries):
                other = other.to_sparse(fill_value=self.fill_value)
            return _sparse_series_op(self, other, op, name)
        elif isinstance(other, DataFrame):
            return NotImplemented
        elif np.isscalar(other):
            if isnull(other) or isnull(self.fill_value):
                new_fill_value = np.nan
            else:
                new_fill_value = op(np.float64(self.fill_value),
                                    np.float64(other))

            return SparseSeries(op(self.sp_values, other),
                                index=self.index,
                                sparse_index=self.sp_index,
                                fill_value=new_fill_value,
                                name=self.name)
        else:  # pragma: no cover
            raise TypeError('operation with %s not supported' % type(other))

    wrapper.__name__ = name
    if name.startswith("__"):
        # strip special method names, e.g. `__add__` needs to be `add` when passed
        # to _sparse_series_op
        name = name[2:-2]
    return wrapper


def _sparse_series_op(left, right, op, name):
    left, right = left.align(right, join='outer', copy=False)
    new_index = left.index
    new_name = _maybe_match_name(left, right)

    result = _sparse_array_op(left, right, op, name)
    return SparseSeries(result, index=new_index, name=new_name)


class SparseSeries(Series):

    """Data structure for labeled, sparse floating point data

    Parameters
    ----------
    data : {array-like, Series, SparseSeries, dict}
    kind : {'block', 'integer'}
    fill_value : float
        Defaults to NaN (code for missing)
    sparse_index : {BlockIndex, IntIndex}, optional
        Only if you have one. Mainly used internally

    Notes
    -----
    SparseSeries objects are immutable via the typical Python means. If you
    must change values, convert to dense, make your changes, then convert back
    to sparse
    """
    _subtyp = 'sparse_series'

    def __init__(self, data, index=None, sparse_index=None, kind='block',
                 fill_value=None, name=None, dtype=None, copy=False,
                 fastpath=False):

        # we are called internally, so short-circuit
        if fastpath:

            # data is an ndarray, index is defined
            data = SingleBlockManager(data, index, fastpath=True)
            if copy:
                data = data.copy()
        else:

            is_sparse_array = isinstance(data, SparseArray)
            if fill_value is None:
                if is_sparse_array:
                    fill_value = data.fill_value
                else:
                    fill_value = nan

            if is_sparse_array:
                if isinstance(data, SparseSeries) and index is None:
                    index = data.index.view()
                elif index is not None:
                    assert(len(index) == len(data))

                sparse_index = data.sp_index
                data = np.asarray(data)

            elif isinstance(data, SparseSeries):
                if index is None:
                    index = data.index.view()

                # extract the SingleBlockManager
                data = data._data

            elif isinstance(data, (Series, dict)):
                if index is None:
                    index = data.index.view()

                data = Series(data)
                data, sparse_index = make_sparse(data, kind=kind,
                                                 fill_value=fill_value)

            elif isinstance(data, (tuple, list, np.ndarray)):
                # array-like
                if sparse_index is None:
                    data, sparse_index = make_sparse(data, kind=kind,
                                                     fill_value=fill_value)
                else:
                    assert(len(data) == sparse_index.npoints)

            elif isinstance(data, SingleBlockManager):
                if dtype is not None:
                    data = data.astype(dtype)
                if index is None:
                    index = data.index.view()
                else:
                    data = data.reindex(index, copy=False)

            else:

                length = len(index)

                if data == fill_value or (isnull(data)
                                          and isnull(fill_value)):
                    if kind == 'block':
                        sparse_index = BlockIndex(length, [], [])
                    else:
                        sparse_index = IntIndex(length, [])
                    data = np.array([])

                else:
                    if kind == 'block':
                        locs, lens = ([0], [length]) if length else ([], [])
                        sparse_index = BlockIndex(length, locs, lens)
                    else:
                        sparse_index = IntIndex(length, index)
                    v = data
                    data = np.empty(length)
                    data.fill(v)

            if index is None:
                index = com._default_index(sparse_index.length)
            index = _ensure_index(index)

            # create/copy the manager
            if isinstance(data, SingleBlockManager):

                if copy:
                    data = data.copy()
            else:

                # create a sparse array
                if not isinstance(data, SparseArray):
                    data = SparseArray(
                        data, sparse_index=sparse_index, fill_value=fill_value, dtype=dtype, copy=copy)

                data = SingleBlockManager(data, index)

        generic.NDFrame.__init__(self, data)

        self.index = index
        self.name = name

    @property
    def values(self):
        """ return the array """
        return self._data._values

    def __array__(self, result=None):
        """ the array interface, return my values """
        return self._data._values

    def get_values(self):
        """ same as values """
        return self._data._values.to_dense().view()

    @property
    def block(self):
        return self._data._block

    @property
    def fill_value(self):
        return self.block.fill_value

    @fill_value.setter
    def fill_value(self, v):
        self.block.fill_value = v

    @property
    def sp_index(self):
        return self.block.sp_index

    @property
    def sp_values(self):
        return self.values.sp_values

    @property
    def npoints(self):
        return self.sp_index.npoints

    @classmethod
    def from_array(cls, arr, index=None, name=None, copy=False, fill_value=None, fastpath=False):
        """
        Simplified alternate constructor
        """
        return cls(arr, index=index, name=name, copy=copy, fill_value=fill_value, fastpath=fastpath)

    @property
    def _constructor(self):
        return SparseSeries

    @property
    def kind(self):
        if isinstance(self.sp_index, BlockIndex):
            return 'block'
        elif isinstance(self.sp_index, IntIndex):
            return 'integer'

    def as_sparse_array(self, kind=None, fill_value=None, copy=False):
        """ return my self as a sparse array, do not copy by default """

        if fill_value is None:
            fill_value = self.fill_value
        if kind is None:
            kind = self.kind
        return SparseArray(self.values,
                           sparse_index=self.sp_index,
                           fill_value=fill_value,
                           kind=kind,
                           copy=copy)

    def __len__(self):
        return len(self.block)

    def __unicode__(self):
        # currently, unicode is same as repr...fixes infinite loop
        series_rep = Series.__unicode__(self)
        rep = '%s\n%s' % (series_rep, repr(self.sp_index))
        return rep

    def __array_wrap__(self, result):
        """
        Gets called prior to a ufunc (and after)
        """
        return self._constructor(result,
                                 index=self.index,
                                 sparse_index=self.sp_index,
                                 fill_value=self.fill_value,
                                 copy=False).__finalize__(self)

    def __array_finalize__(self, obj):
        """
        Gets called after any ufunc or other array operations, necessary
        to pass on the index.
        """
        self.name = getattr(obj, 'name', None)
        self.fill_value = getattr(obj, 'fill_value', None)

    def _reduce(self, op, name, axis=0, skipna=True, numeric_only=None,
                filter_type=None, **kwds):
        """ perform a reduction operation """
        return op(self.get_values(), skipna=skipna, **kwds)

    def __getstate__(self):
        # pickling
        return dict(_typ=self._typ,
                    _subtyp=self._subtyp,
                    _data=self._data,
                    fill_value=self.fill_value,
                    name=self.name)

    def _unpickle_series_compat(self, state):

        nd_state, own_state = state

        # recreate the ndarray
        data = np.empty(nd_state[1], dtype=nd_state[2])
        np.ndarray.__setstate__(data, nd_state)

        index, fill_value, sp_index = own_state[:3]
        name = None
        if len(own_state) > 3:
            name = own_state[3]

        # create a sparse array
        if not isinstance(data, SparseArray):
            data = SparseArray(
                data, sparse_index=sp_index, fill_value=fill_value, copy=False)

        # recreate
        data = SingleBlockManager(data, index, fastpath=True)
        generic.NDFrame.__init__(self, data)

        self._set_axis(0, index)
        self.name = name

    def __iter__(self):
        """ forward to the array """
        return iter(self.values)

    def _set_subtyp(self, is_all_dates):
        if is_all_dates:
            object.__setattr__(self, '_subtyp', 'sparse_time_series')
        else:
            object.__setattr__(self, '_subtyp', 'sparse_series')

    def _get_val_at(self, loc):
        """ forward to the array """
        return self.block.values._get_val_at(loc)

    def __getitem__(self, key):
        """

        """
        try:
            return self._get_val_at(self.index.get_loc(key))

        except KeyError:
            if isinstance(key, (int, np.integer)):
                return self._get_val_at(key)
            raise Exception('Requested index not in this series!')

        except TypeError:
            # Could not hash item, must be array-like?
            pass

        # is there a case where this would NOT be an ndarray?
        # need to find an example, I took out the case for now

        key = _values_from_object(key)
        dataSlice = self.values[key]
        new_index = Index(self.index.view(ndarray)[key])
        return self._constructor(dataSlice, index=new_index).__finalize__(self)

    def _set_with_engine(self, key, value):
        return self.set_value(key, value)

    def abs(self):
        """
        Return an object with absolute value taken. Only applicable to objects
        that are all numeric

        Returns
        -------
        abs: type of caller
        """
        res_sp_values = np.abs(self.sp_values)
        return self._constructor(res_sp_values, index=self.index,
                                 sparse_index=self.sp_index,
                                 fill_value=self.fill_value)

    def get(self, label, default=None):
        """
        Returns value occupying requested label, default to specified
        missing value if not present. Analogous to dict.get

        Parameters
        ----------
        label : object
            Label value looking for
        default : object, optional
            Value to return if label not in index

        Returns
        -------
        y : scalar
        """
        if label in self.index:
            loc = self.index.get_loc(label)
            return self._get_val_at(loc)
        else:
            return default

    def get_value(self, label, takeable=False):
        """
        Retrieve single value at passed index label

        Parameters
        ----------
        index : label
        takeable : interpret the index as indexers, default False

        Returns
        -------
        value : scalar value
        """
        loc = label if takeable is True else self.index.get_loc(label)
        return self._get_val_at(loc)

    def set_value(self, label, value, takeable=False):
        """
        Quickly set single value at passed label. If label is not contained, a
        new object is created with the label placed at the end of the result
        index

        Parameters
        ----------
        label : object
            Partial indexing with MultiIndex not allowed
        value : object
            Scalar value
        takeable : interpret the index as indexers, default False

        Notes
        -----
        This method *always* returns a new object. It is not particularly
        efficient but is provided for API compatibility with Series

        Returns
        -------
        series : SparseSeries
        """
        values = self.to_dense()

        # if the label doesn't exist, we will create a new object here
        # and possibily change the index
        new_values = values.set_value(label, value, takeable=takeable)
        if new_values is not None:
            values = new_values
        new_index = values.index
        values = SparseArray(
            values, fill_value=self.fill_value, kind=self.kind)
        self._data = SingleBlockManager(values, new_index)
        self._index = new_index

    def _set_values(self, key, value):

        # this might be inefficient as we have to recreate the sparse array
        # rather than setting individual elements, but have to convert
        # the passed slice/boolean that's in dense space into a sparse indexer
        # not sure how to do that!
        if isinstance(key, Series):
            key = key.values

        values = self.values.to_dense()
        values[key] = _index.convert_scalar(values, value)
        values = SparseArray(
            values, fill_value=self.fill_value, kind=self.kind)
        self._data = SingleBlockManager(values, self.index)

    def to_dense(self, sparse_only=False):
        """
        Convert SparseSeries to (dense) Series
        """
        if sparse_only:
            int_index = self.sp_index.to_int_index()
            index = self.index.take(int_index.indices)
            return Series(self.sp_values, index=index, name=self.name)
        else:
            return Series(self.values.to_dense(), index=self.index, name=self.name)

    @property
    def density(self):
        r = float(self.sp_index.npoints) / float(self.sp_index.length)
        return r

    def copy(self, deep=True):
        """
        Make a copy of the SparseSeries. Only the actual sparse values need to
        be copied
        """
        new_data = self._data
        if deep:
            new_data = self._data.copy()

        return self._constructor(new_data,
                                 sparse_index=self.sp_index,
                                 fill_value=self.fill_value).__finalize__(self)

    def reindex(self, index=None, method=None, copy=True, limit=None):
        """
        Conform SparseSeries to new Index

        See Series.reindex docstring for general behavior

        Returns
        -------
        reindexed : SparseSeries
        """
        new_index = _ensure_index(index)

        if self.index.equals(new_index):
            if copy:
                return self.copy()
            else:
                return self
        return self._constructor(self._data.reindex(new_index, method=method, limit=limit, copy=copy),
                                 index=new_index).__finalize__(self)

    def sparse_reindex(self, new_index):
        """
        Conform sparse values to new SparseIndex

        Parameters
        ----------
        new_index : {BlockIndex, IntIndex}

        Returns
        -------
        reindexed : SparseSeries
        """
        if not isinstance(new_index, splib.SparseIndex):
            raise TypeError('new index must be a SparseIndex')

        block = self.block.sparse_reindex(new_index)
        new_data = SingleBlockManager(block, self.index)
        return self._constructor(new_data, index=self.index,
                                 sparse_index=new_index,
                                 fill_value=self.fill_value).__finalize__(self)

    def take(self, indices, axis=0, convert=True):
        """
        Sparse-compatible version of ndarray.take

        Returns
        -------
        taken : ndarray
        """
        new_values = SparseArray.take(self.values, indices)
        new_index = self.index.take(indices)
        return self._constructor(new_values, index=new_index).__finalize__(self)

    def cumsum(self, axis=0, dtype=None, out=None):
        """
        Cumulative sum of values. Preserves locations of NaN values

        Returns
        -------
        cumsum : Series or SparseSeries
        """
        new_array = SparseArray.cumsum(self.values)
        if isinstance(new_array, SparseArray):
            return self._constructor(new_array, index=self.index, sparse_index=new_array.sp_index).__finalize__(self)
        return Series(new_array, index=self.index).__finalize__(self)

    def dropna(self, axis=0, inplace=False, **kwargs):
        """
        Analogous to Series.dropna. If fill_value=NaN, returns a dense Series
        """
        # TODO: make more efficient
        axis = self._get_axis_number(axis or 0)
        dense_valid = self.to_dense().valid()
        if inplace:
            raise NotImplementedError("Cannot perform inplace dropna"
                                      " operations on a SparseSeries")
        if isnull(self.fill_value):
            return dense_valid
        else:
            dense_valid = dense_valid[dense_valid != self.fill_value]
            return dense_valid.to_sparse(fill_value=self.fill_value)

    def shift(self, periods, freq=None, **kwds):
        """
        Analogous to Series.shift
        """
        from pandas.core.datetools import _resolve_offset

        offset = _resolve_offset(freq, kwds)

        # no special handling of fill values yet
        if not isnull(self.fill_value):
            dense_shifted = self.to_dense().shift(periods, freq=freq,
                                                  **kwds)
            return dense_shifted.to_sparse(fill_value=self.fill_value,
                                           kind=self.kind)

        if periods == 0:
            return self.copy()

        if offset is not None:
            return self._constructor(self.sp_values,
                                     sparse_index=self.sp_index,
                                     index=self.index.shift(periods, offset),
                                     fill_value=self.fill_value).__finalize__(self)

        int_index = self.sp_index.to_int_index()
        new_indices = int_index.indices + periods
        start, end = new_indices.searchsorted([0, int_index.length])

        new_indices = new_indices[start:end]

        new_sp_index = IntIndex(len(self), new_indices)
        if isinstance(self.sp_index, BlockIndex):
            new_sp_index = new_sp_index.to_block_index()

        return self._constructor(self.sp_values[start:end].copy(),
                                 index=self.index,
                                 sparse_index=new_sp_index,
                                 fill_value=self.fill_value).__finalize__(self)

    def combine_first(self, other):
        """
        Combine Series values, choosing the calling Series's values
        first. Result index will be the union of the two indexes

        Parameters
        ----------
        other : Series

        Returns
        -------
        y : Series
        """
        if isinstance(other, SparseSeries):
            other = other.to_dense()

        dense_combined = self.to_dense().combine_first(other)
        return dense_combined.to_sparse(fill_value=self.fill_value)

# overwrite series methods with unaccelerated versions
ops.add_special_arithmetic_methods(SparseSeries, use_numexpr=False,
                                   **ops.series_special_funcs)
ops.add_flex_arithmetic_methods(SparseSeries, use_numexpr=False,
                                **ops.series_flex_funcs)
# overwrite basic arithmetic to use SparseSeries version
# force methods to overwrite previous definitions.
ops.add_special_arithmetic_methods(SparseSeries, _arith_method,
                                   radd_func=operator.add, comp_method=None,
                                   bool_method=None, use_numexpr=False, force=True)

# backwards compatiblity
SparseTimeSeries = SparseSeries
