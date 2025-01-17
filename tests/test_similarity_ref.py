import pytest
import os
import numpy as np
import pandas as pd
import nibabel as nib
from pathlib import Path
import seaborn as sns
from pyrelimri.similarity import image_similarity
from pyrelimri.tetrachoric_correlation import tetrachoric_corr
from pyrelimri.brain_icc import voxelwise_icc
from pyrelimri.icc import sumsq_icc
from collections import namedtuple
from nilearn.masking import compute_multi_brain_mask
from hypothesis import given, strategies as st
from hypothesis.extra.numpy import arrays


def generate_img_pair(r: float, dir: Path, use_mask: bool = False, tol: float = .001,
                      imgdims: list = None,
                      maskdims: list = None) -> namedtuple:
    """
    r: correlation bw images
    dir: Path for saving files
    use_mask: bool, create mask and mask data
    tol: tolerance for correlation value - lower than .001 will make it really slow
    returns:
        images: path to two image files with specified correlation
        mask: path to mask image, all ones if use_mask==False
    """
    imgpair = namedtuple("ImgPair", "tol r images maskimg")
    imgpair.images = []
    imgpair.r = r
    imgpair.tol = tol

    rng = np.random.default_rng()

    if imgdims is None:
        imgdims = [64, 64, 32]
    nvox = np.prod(imgdims)
    if use_mask:
        if maskdims is None:
            maskdims = [round(i/2) for i in imgdims]
        mask = np.zeros(imgdims).astype('int')
        mask[:maskdims[0], :maskdims[1], :maskdims[2]] = 1
    else:
        mask = np.ones(imgdims)
        
    maskvox = mask.reshape(nvox)

    empirical_r = 10
    while (np.abs(empirical_r - r) > tol):
        data = rng.multivariate_normal(mean=[0,0],
            cov=[[1,r],[r,1]], size=nvox)
        empirical_r = np.corrcoef(data[maskvox == 1, :].T)[0,1]
    
    for i in range(2):
        imgpair.images.append(dir / f'testimg_{i}.nii.gz')
        tmpimg = nib.Nifti1Image((maskvox * data[:, i]).reshape(imgdims),
            affine=np.eye(4))
        tmpimg.to_filename(imgpair.images[-1])
    imgpair.mask = dir / 'mask.nii.gz'
    maskimg = nib.Nifti1Image(mask, affine=np.eye(4))
    maskimg.to_filename(imgpair.mask)
    return imgpair
    

@pytest.fixture(scope="session")
def image_pair(tmp_path_factory):
    tmpdir = tmp_path_factory.mktemp("data")
    return generate_img_pair(r=0.5, dir=tmpdir)


def test_image_pair_smoke(image_pair):
    assert image_pair.images is not None


def test_image_pair_images(image_pair):
    for imgfile in image_pair.images + [image_pair.mask]:
        img = nib.load(imgfile)
        assert img is not None

def create_dummy_nifti(shape, affine, filepath):
    data = np.random.rand(*shape)
    img = nib.Nifti1Image(data, affine)
    nib.save(img, str(filepath))


def test_session_lengths_mismatch(tmp_path_factory):
    tmpdir = tmp_path_factory.mktemp("data")

    # Test case with different session lengths
    multisession_list = [
        [tmpdir / "sub-00_ses1_Contrast-A_bold.nii.gz",
         tmpdir / "sub-01_ses1_Contrast-A_bold.nii.gz"],
        [tmpdir / "sub-00_ses2_Contrast-A_bold.nii.gz",
         tmpdir / "sub-01_ses2_Contrast-A_bold.nii.gz",
         tmpdir / "sub-03_ses2_Contrast-A_bold.nii.gz"]
    ]

    icc_type = "icc_3"

    # Create dummy NIfTI files
    shape = (97, 115, 97)
    affine = np.eye(4)
    for session in multisession_list:
        for filepath in session:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            create_dummy_nifti(shape, affine, filepath)

    mask = compute_multi_brain_mask(target_imgs=[
        tmpdir / "sub-00_ses2_Contrast-A_bold.nii.gz",
        tmpdir / "sub-01_ses2_Contrast-A_bold.nii.gz",
        tmpdir / "sub-03_ses2_Contrast-A_bold.nii.gz"
    ])

    mask_path = tmpdir / 'test_mask.nii.gz'
    nib.save(mask, mask_path)

    # The assertion should raise an exception
    with pytest.raises(AssertionError):
        voxelwise_icc(multisession_list, mask, icc_type)


@pytest.mark.parametrize("measure", ['Dice', 'Jaccard'])
def test_image_similarity(image_pair, measure):
    imgsim = image_similarity(
        image_pair.images[0], image_pair.images[1], image_pair.mask,
        thresh=1, similarity_type=measure
    )
    assert imgsim is not None

def test_spearman_similarity(image_pair):
    spearman_sim = image_similarity(
        image_pair.images[0], image_pair.images[1], similarity_type='spearman')
    assert abs(spearman_sim - 0.5) < 0.1, "The similarity is not close to 0.5."

def test_image_similarity_spearman_value_error(image_pair):
    imgfile1 = image_pair.images[0]
    imgfile2 = image_pair.images[1]
    mask = None
    thresh = 0.5
    similarity_type = "spearman"
    with pytest.raises(ValueError):
        image_similarity(imgfile1, imgfile2, mask=mask, thresh=thresh, similarity_type=similarity_type)

#@pytest.mark.parametrize("corr", [.50, .60,.45])
def test_calculate_icc1():
    data = sns.load_dataset('anagrams')
    # subset to only divided attnr measure occ
    a_wd = data[data['attnr'] == 'divided']
    a_ld = pd.DataFrame(
        pd.melt(a_wd,
                id_vars="subidr",
                value_vars=["num1", "num2", "num3"],
                var_name="sess",
                value_name="vals"))

    icc = sumsq_icc(df_long=a_ld, sub_var="subidr",
                   sess_var="sess", value_var="vals", icc_type='icc_1')

    assert np.allclose(icc[0], -0.05, atol=.01)


def test_calculate_icc2():
    data = sns.load_dataset('anagrams')
    # subset to only divided attnr measure occ
    a_wd = data[data['attnr'] == 'divided']
    a_ld = pd.DataFrame(
        pd.melt(a_wd,
                id_vars="subidr",
                value_vars=["num1", "num2", "num3"],
                var_name="sess",
                value_name="vals"))

    icc = sumsq_icc(df_long=a_ld, sub_var="subidr",
                   sess_var="sess",value_var="vals", icc_type='icc_2')
    assert np.allclose(icc[0], 0.11, atol=.01)

# tetrachoric tests
def test_tetrachoric_corr():
    assert np.allclose(
        tetrachoric_corr(np.array([0, 0, 1, 1]),
                         np.array([0, 1, 0, 1])),
        0.0)
    assert np.allclose(
        tetrachoric_corr(np.array([0, 0, 1, 1]),
                         np.array([0, 0, 1, 1])),
        1.0)
    assert np.allclose(
        tetrachoric_corr(np.array([0, 0, 1, 1]),
                         np.array([1, 1, 0, 0])),
        -1.0)

def test_tetrachoric_corr_nanhandling():
    assert np.isnan(
        tetrachoric_corr(np.array([0, 0, 1, 1]),
                         np.array([1, 1, 1, 1])))

# property based testing with a range of arrays
@given(vec=arrays(np.int8, (2, 24), elements=st.integers(0, 100)))
def test_tetrachoric_corr_hypothesis(vec):
    tc = tetrachoric_corr(vec[0, :], vec[1, :])
    if (vec[0, :] == vec[1, :]).all():
        assert tc == 1.0
    else:
        B = sum(np.logical_and(vec[0, :] == 0, vec[1, :] == 1))
        C = sum(np.logical_and(vec[0, :] == 1, vec[1, :] == 0))
        # should return nan in these cases
        if B == 0 or C == 0:
            assert np.isnan(tc)
        else:
            assert tc <= 1.0 and tc >= -1.0