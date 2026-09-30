# External evidence sources: EU election abstention

This folder keeps local source documents for the D1 prototype. The prototype should create anonymized summaries and aggregate survey evidence from these reports; it should not treat them as respondent-level records or raw focus-group transcripts.

## Files

- `external/eu-parliament-voting-2009/post_electoral_survey_2009_en.pdf` — Special Eurobarometer 320 / Wave 71.3 post-election report. Survey fieldwork: June–July 2009; the report describes 26,830 interviews.
  Source: https://www.europarl.europa.eu/pdf/eurobarometre/28_07/EB71.3_post-electoral_final_report_EN.pdf
- `external/eu-parliament-voting-2009/focus_groups_abstainers_2012_en.pdf` — qualitative report on impulsive and unspecified abstainers. Fieldwork: 6–17 February 2012; three focus groups per EU Member State, each with 8–12 participants. The report explicitly says the groups were not representative of the whole population.
  Source: https://www.europarl.europa.eu/pdf/eurobarometre/2012/research/121126_EurobarometerQualitativeStudy_Abstainers_EN.pdf

Related Kaggle listing: https://www.kaggle.com/datasets/eu-parliament/voting-behaviour-survey-2009-european-elections

## Use and limitations

- Keep the 2009 survey and 2012 focus groups as distinct evidence streams; they are separated in time and are not the same participant sample.
- Record the evidence method, year, source, denominator, and whether a statement is an aggregate finding or a qualitative theme.
- Focus-group findings are exploratory and non-representative. Survey associations and self-reported reasons do not establish the cause of an individual's abstention.
- These PDFs contain published reports, not raw survey-response rows or verbatim focus-group transcripts.
- Use them to manually prepare concise, cited, anonymized evidence summaries; keep demo/test records synthetic unless the project scope is deliberately revised.

## Reuse

The European Parliament's general legal notice says reuse of relevant EU-owned material is generally permitted when the complete item is reproduced and the source is acknowledged, subject to any item-specific conditions. Preserve these PDFs unchanged and check their own notices before public redistribution.
Legal notice: https://www.europarl.europa.eu/legal-notice/en/

The PDF files are local external data and are ignored by Git pending a separate publication/licensing decision. This README records provenance and remains part of the project files.