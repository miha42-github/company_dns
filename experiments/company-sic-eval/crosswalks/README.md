Official correspondence tables were used in a research experiment only
(docs/plans/company-sic-match.md sec. 11.1b) and are **not used by the product** and
**not kept in this repository**: their licensing is unresolved (none of the files
states a licence; the UN's general copyright page requires written permission for
reproduction). The data files were deleted on 2026-10-04 at the user's request.

To reproduce the experiment (`../official_crosswalks.py`, `../crosswalk_eval2.py`),
check each publisher's terms first, then place the files in this folder:

* `ISIC4_NACE2.txt`: UN Statistics Division,
  https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/ISIC4_NACE2/ISIC4_NACE2.txt
* `ISIC31_ISIC4.txt`: UNSD, .../tables/ISIC/ISIC31_ISIC4/ISIC31_ISIC4.txt
* `ISIC-USSIC.csv`: UNSD, .../tables/ISIC/ISIC_USSIC/ISIC-USSIC.csv
* `jsic13_isic4.xls`: Statistics Bureau of Japan (MIC), https://www.soumu.go.jp/main_content/000315013.xls,
  converted to `jsic13_isic4.csv` (columns `JSIC13,ISIC4`; needs an Excel reader such as xlrd).
