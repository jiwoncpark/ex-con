"""A file containing utils for processing.py
"""

import numpy as np
from scipy.spatial import KDTree

__all__ = ['gen_labels', 'strip2RAdec', 'gen_sightlines', 'compute_X']

def gen_labels(arr):
    """Generate y labels for given raw DES data by
    getting the mean magnitude of the objects and dividing
    it by 1000.

    Parameters
    ----------
    arr : np.ndarray
        Numpy ndarray of shape (N,) where each entry corresponds to a star/galaxy from DES data

    Returns
    -------
    arr : np.ndarray
    """
    return np.mean([obj[39] for obj in arr]) / 1000

def strip2RAdec(arr):
    """Strip the raw DES data into a set of (ra, dec) coordinates
    for stars and galaxies.

    Parameters
    ----------
    arr : np.ndarray
        array of shape (N,) where each row corresponds to information about a star/galaxy.

    Returns
    -------
    coords : np.ndarray
        array of shape (N,2) where each row corresponds to (ra, dec) of a star/galaxy.
    """
    return np.array([[x[1], x[2]] for x in arr])


def get_x_i(sightline, tree, arr, THRESHOLD=0.0333333333):
    """Given a sightline and raw DES array, get all
    galaxies within a threshold angular distance of the sightline.

    Parameters
    ----------
    sightline : np.ndarray
        A tuple representing the sightline
    tree : np.ndarray
        kd-tree constructed with the ra and dec of all of the elements of arr
    arr : np.ndarray
        Raw DES data
    THRESHOLD : float
        In degrees, the farthest galaxies that should be considered for a LOS

    Returns
    -------
    x_i : list
        A list where each element is a galaxy within a threshold of the LOS,
        ordered by distance from LOS
    """

    # filter by the ones within the THRESHOLD distance to the LOS
    x_i = arr[tree.query_ball_point(sightline, THRESHOLD)]
    x_i = list(x_i)

    # order by distance from LOS
    x_i = sorted(x_i, key=lambda x: np.linalg.norm(np.array(x[1] - sightline[0], x[2] - sightline[1])))

    return x_i


def compute_X(arr, sightlines):
    """Given some grid of k sight lines and some raw DES data,
    compute the k training input sets.

    Parameters
    ----------
    arr : np.ndarray
        A NumPy array of shape (N,) containing the raw data from DES.

    Returns
    -------
    LOS : np.ndarray
        A NumPy ndarray of shape (k,) where each element is a list of galaxies
        within a radius of 2 arcminutes of the LOS
    """

    k = sightlines.shape[0]

    X = np.empty((k, ), dtype='O')
    coords = strip2RAdec(arr)
    tree = KDTree(coords)

    for i, sightline in enumerate(sightlines):
        X[i] = get_x_i(sightline, tree, arr)

    return X

