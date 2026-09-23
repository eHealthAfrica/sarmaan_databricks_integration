# SARMAAN pipeline data schema

What each pipeline reads from KoboToolbox and what it writes to Postgres.

- **Flow:** Kobo export → stager (map, recode, audit) → `STAGING_*.xlsx` + audit PDF → human review → loader → Postgres
- **Types:** every column is read and loaded as text (`dtype=str`). Postgres column types come from the existing target tables.
- **Kobo system columns:** these are added to every export and used for keys and joins: `_id`, `_uuid`, `_submission_time`, `_index` (main sheet); `_index`, `_parent_index`, `_submission__id`, `_submission__uuid` (repeat sheets).
- **Mapping CSVs:** for AMR and Pharmacy, the Kobo-column → DB-column mapping lives in the mapping CSVs (`kobo_name`, `db_name`, `action`), not in this repo. The DB column lists below cover the columns the code refers to. The CSV's `db_name` column gives the full, ordered list.

| Pipeline | Kobo source | Target |
|---|---|---|
| AMR | API: asset `aks5TQaYbfgGvhCigjGAvp` (SARMAAN II BASELINE ZAMFARA AMR LIVE FORM), 3 sheets | `sarmaan_2.sarmaan2data`: `amr_household_information`, `amr_mother_information`, `amr_child_information` |
| Pharmacy | API: asset `aLcuF4wGExja3LrSZxEEnB` (SARMAAN II BASELINE ZAMFARA PHARMACY LIVE FORM), 1 sheet | `sarmaan_2.sarmaan2data.pharmacy_information` |
| Mortality | **Local file** `MORTALITY_DIR/kobo_exports/mortality_export.xlsx`, 3 sheets | `mortality.mortalitydata`: `household_mortality`, `females_mortality`, `pregnancy_mortality` |

---

## 1. AMR

### Pull from Kobo
- **Export:** `https://kf.kobotoolbox.org/api/v2/assets/aks5TQaYbfgGvhCigjGAvp/export-settings/esBAy9ZfJutvuffFDgu3Bqt/data.xlsx`, with English labels as the column headers.
- **Sheets:**

| Export sheet | Read by | Form section |
|---|---|---|
| `SARMAAN II BASELINE ZAMFARA ...` (main, one row per household) | House, Mother and Child stagers | Main form |
| `mother_information` (one row per mother) | Mother and Child stagers | Repeat `mother_information` |
| `child_info` (one row per child) | Child stager | Repeat `child_info` (nested in mother) |

**Join keys the stagers build:**
- **Mother → household:** `mother._submission__uuid` = `household._uuid`. This brings in `unique_code`, which becomes `household_code_pull`, plus `state_name`, `Confirm your LGA`, `Confirm your ward`, `Confirm your community` and `Q10. Cycle`.
- **Child → mother:** `child._submission__uuid + "_" + child._parent_index` = `mother._submission__uuid + "_" + mother._index`. This brings in `Mother ID`, which becomes `mother_code`.
- **Child → household:** `child._submission__uuid` = `household._uuid`. This brings in `unique_code`, which becomes `household_code`, plus the geo columns.

**Main sheet (household)**

<details><summary>146 form fields (click to expand)</summary>

| Kobo field | Type | Question label |
|---|---|---|
| `start` | start |  |
| `end` | end |  |
| `start-geopoint` | start-geopoint |  |
| `username` | username |  |
| `deviceid` | deviceid |  |
| `phonenumber` | phonenumber |  |
| `audit` | audit |  |
| `form_version` | calculate |  |
| `start_iso` | calculate |  |
| `end_iso` | calculate |  |
| `concat_user` | calculate |  |
| `user_confirm` | text | confirm user and phone number |
| `concat_enu` | text | confirm enumerator and phone number |
| `enum_id` | calculate | Q5. Select your enumerator ID |
| `enum_batch` | calculate | Batch (A or B) |
| `enum_settlement` | calculate | Assigned settlement code |
| `enum_settlement_label` | calculate | Assigned settlement name |
| `enum_lga_code` | calculate |  |
| `enum_role` | calculate |  |
| `enum_phone` | calculate |  |
| `enum_name_cdd` | calculate |  |
| `enum_name` | calculate |  |
| `entry_mode` | select_one | **How are you completing this form?** |
| `signed_consent` | select_one | Have you fully explained this research to the household members and given suffic |
| `household_head_consent` | select_one | Q1. Household head agrees to be interviewed |
| `date_of_consent` | date | Date of Consent |
| `witness` | select_one | Was there a witness present? |
| `witness_name` | text | Witness Name |
| `witness_name_proper` | calculate |  |
| `start_time` | time | Start time |
| `states` | calculate | Q2. State |
| `lgas` | calculate | Q3. Local Government Area |
| `wards` | select_one_from_file | Q4. Ward |
| `community_name` | select_one_from_file | Q5. Community Name |
| `settlement_match` | calculate |  |
| `team_count` | calculate |  |
| `household_no1` | select_one | Q6. Household number |
| `name_parent` | text | Q7. Name of household head giving consent or designee |
| `name_parent_proper` | calculate |  |
| `settlement_type` | select_one | Choose the settlement type |
| `communication_language` | select_one | Q8. Language of communication |
| `other_communication_language` | text | Kindly input your language of communication not on the list above |
| `gps_capture` | geopoint | Q9. GPS coordinates (capture from device) |
| `gps_desk_lat` | calculate |  |
| `gps_desk_lon` | calculate |  |
| `gps_desk` | calculate |  |
| `gps` | calculate |  |
| `bbox_min_lat` | calculate |  |
| `bbox_max_lat` | calculate |  |
| `bbox_min_lon` | calculate |  |
| `bbox_max_lon` | calculate |  |
| `polygon_inside` | calculate |  |
| `polygon_message` | calculate |  |
| `state_name` | calculate |  |
| `lga_name` | calculate | Confirm your LGA |
| `ward_name` | calculate | Confirm your ward |
| `community_label` | calculate | Confirm your community |
| `cycle` | select_one | Q10. Cycle |
| `unique` | calculate |  |
| `unique_code` | calculate |  |
| `hh_id` | text | Household ID is: ${unique_code} |
| `check_location` | acknowledge | ⚠️Confirm the following response LGA: ${lga_name}, Ward: ${ward_name}, Community |
| `household_head` | select_one | Q1. Are you the head of the household? |
| `household_headname` | text | Q2. Name of the head of the household? |
| `household_headname_proper` | calculate |  |
| `gender_hh` | select_one | Q3. Gender of the head of the household? |
| `marital_status_hh` | select_one | Q3a. Marital status of head of household |
| `age_hhead` | integer | Q4. Age as at last birthday of head of the Household |
| `name_questionnaire` | text | Q5. Name of person completing the household questionnaire |
| `name_questionnaire_proper` | calculate |  |
| `hh_signature` | image | Signature of person completing the household questionnaire |
| `hh_name` | calculate |  |
| `live_here` | select_one | Q6. Does ${name_questionnaire} usually live here? |
| `stay_last_night` | select_one | Q7. Did ${name_questionnaire} stay here last night? |
| `age_hhhead` | integer | Q8. Age as at last birthday of ${name_questionnaire}? |
| `gender_phh` | select_one | Q9. Gender of person answering the household questionnaire |
| `household_relationship` | select_one | Q10. What is the relationship with the head of the household? |
| `other_household_relationship` | text | Kindly specify your relationship to the household head |
| `hh_no` | select_one | Do you have a phone number? Kanada lamba waya ne? |
| `hh_phone_no` | text | Phone number Lamba waya |
| `school` | select_one | Q11. Have you had any form of education? Kin taba shiga makaranta? |
| `q_western` | select_multiple | Q12. Was it Quranic or Western? Makarantar Islamiyya ko boko? |
| `hh_education_level` | select_one | Q13. What is the highest level of school you attended: primary, secondary, or hi |
| `duration_level_pri` | integer | Q14. What is the highest class you completed at that level? If completed less th |
| `duration_level_sec` | integer | Q14. What is the highest class you completed at that level? If completed less th |
| `occupation_h` | select_one | Q15. Household head’s occupation |
| `own_phone` | select_one | Q16. Do you own a mobile phone? Ki na da wayar hannu? |
| `smart_phone` | select_one | Q17. Is your mobile phone a smart phone? Wayar ki babbar waya ce? |
| `note6` | select_one | Does your household own any of the following? |
| `television` | select_one | Q18. Does your household have a television? |
| `electric_iron` | select_one | Q19. Does your household have an electric iron? |
| `fan` | select_one | Q20. Does your household have a fan? |
| `refrigerator` | select_one | Q21. Does your household have a refrigerator? |
| `electricity` | select_one | Q22. Does your household have electricity? |
| `generator` | select_one | Q23. Does your household have a generator? |
| `bank_account` | select_one | Q24. Does any member of the household have a bank account? |
| `watch` | select_one | Q25. Does any member of the household have a watch? |
| `animal_mobility` | select_one | Q26.Does your household have any of the following (Donkey,Camel,Cattle,Horse)? |
| `truck` | select_one | Q27. Does your household have truck? |
| `bicycle` | select_one | Q28. Does your household have bicycle? |
| `tricycle` | select_one | Q29. Does your household have tricycle? |
| `computer` | select_one | Q30. Does your household have computer? |
| `table` | select_one | Q31. Does your household have table? |
| `aircondition` | select_one | Q32. Does your household have air condition? |
| `floor_material` | select_one | Q33. What is the main material of the floor? |
| `other_floor_material` | text | Kindly specify the kind of floor material not on the above list |
| `wall_material` | select_one | Q34. What is the main material of the wall ? |
| `other_wall_material` | text | Kindly specify the kind of wall material not on the above list |
| `cooking_stove` | select_one | Q35. What type of cooking stove is mainly used for cooking? |
| `cooking_stove_others` | select_one | Kindly select any other cooking stove not on the list above |
| `water_source` | select_one | Q36. What is the main source of drinking water for members of your household? |
| `other_water_source` | text | Kindly specify any other water source not mentioned above |
| `water_source2` | select_one | Q37. What is the main source of water used by your household for other purposes  |
| `other_water_source2` | text | Kindly specify any other water source not listed above |
| `bedroom` | integer | Q38. Number of sleeping rooms in the house? |
| `toilet_facility` | select_one | Q39. What kind of toilet facility do members of your household usually use |
| `other_toilet_facility` | text | Kindly specify any other toilet facility not mentioned above |
| `shared_toilet` | select_one | Q40. Do you share this toilet facility with other households? |
| `toilet_location` | select_one | Q41. Where is this toilet facility located? |
| `rubbish` | select_one | Q42. How is rubbish (solid waste) disposed of? |
| `rubbish_other` | text | Kindly specify any other way that rubbish is disposed of not on this list |
| `washing_hand` | select_one | Q43. Can you please show me where members of your household most often wash thei |
| `washing_hand_other` | text | Kindly specify any other places that you wash your hands not list above |
| `washing_place` | select_one | Q44. If there is a washing place, what are the things observed? |
| `no_household` | integer | Q45. Total Number of persons in household |
| `no_wives_1_59` | integer | Q46. How many of the caregivers/mothers have children 0-59 months? |
| `no_0_59` | integer | Q47. How many children in the household are 0-59 months of age? |
| `no_u5` | integer | Q48. How many children in the household are 1-59 months of age? |
| `child_left` | calculate |  |
| `no_28days` | integer | Q49. How many children in the household are 0 - 28 days of age? |
| `mothers_count` | integer | Q50. How many mothers/caregivers are to be enrolled for this survey? |
| `photo` | image | Please take a picture of the sample manifest showing the name and ID of the elig |
| `comment` | text | Comments |
| `count_mothers_actual` | calculate |  |
| `count_mothers_with_u5` | calculate |  |
| `count_children_actual` | calculate |  |
| `sum_mother_neonates` | calculate |  |
| `mothers_count_match` | calculate |  |
| `wives_1_59_match` | calculate |  |
| `children_loop_match` | calculate |  |
| `neonates_match` | calculate |  |
| `any_count_mismatch` | calculate |  |
| `sum_mother_no_u5` | calculate |  |
| `child_count_match` | calculate |  |
| `repeat_integrity_ok` | calculate |  |
| `repeat_integrity_block` | text | 🛑 **DATA INTEGRITY ISSUE** The number of mother or child entries does not match  |

</details>

**`mother_information` sheet**

<details><summary>17 form fields (click to expand)</summary>

| Kobo field | Type | Question label |
|---|---|---|
| `mother_id_001` | calculate |  |
| `mother_signature` | image | Signature of mother ${mother_id_001} |
| `householdid` | text | Household ID |
| `fathername` | text | Father Name |
| `mother_id` | calculate |  |
| `unique_code1` | text | Mother ID |
| `mother_name` | text | Q51. Mother ${mother_id_001} name |
| `mother_name_proper` | calculate |  |
| `mother_age` | integer | Q52. Mother's age |
| `education_level` | select_one | Q53. Mother`s Highest Educational Level |
| `marital_status_mother` | select_one | Q53a. Mother's marital status |
| `occupation` | select_one | Q54. Mother’s Occupation |
| `no_children_less_than_1_month` | integer | Q55. Total Number of Children less than 1 month |
| `sum_so_far` | calculate |  |
| `effective_cap` | calculate |  |
| `remaining_for_household` | calculate |  |
| `mother_no_u5` | integer | Q56. Total Number of Children 1 - 59 months |

</details>

**`child_info` sheet**

<details><summary>50 form fields (click to expand)</summary>

| Kobo field | Type | Question label |
|---|---|---|
| `ch_id` | calculate |  |
| `child_id` | calculate |  |
| `householdid_001` | text | Household ID |
| `motherid` | text | Mother ID |
| `father_info` | text | Father Name |
| `mothername` | text | Mother's Name |
| `c_id` | text | Child ID: ${child_id} |
| `child_name` | text | Q61. Name of Child ${ch_id} |
| `child_name_proper` | calculate |  |
| `child_dob` | date | Q62. Date of birth of ${child_name} |
| `c_age` | calculate |  |
| `child_age` | text | Q63. Age of ${child_name}: ${c_age} months |
| `child_gender` | select_one | Q64. ${child_name}'s gender |
| `place_of_delivery` | select_one | Q65. Place of Delivery |
| `feeding_mode` | select_one | Q66. Feeding mode at the first 6 months of life |
| `current_feeding_mode` | select_multiple | Q67. Current Feeding Mode |
| `immunization_status` | select_one | Q68. Was ${child_name} ever immunized? |
| `reason_4_no_immunization` | select_one | Q69. What was the reason for no immunization? |
| `child_been_sick_in_last_3_months` | select_one | Q70. Has your child been sick in the last 3 months? |
| `ari_count` | integer | Q71. Number of Acute Respiratory tract infection (ARI) |
| `fever` | integer | Q72. Number of Acute febrile illness in last 3 months |
| `diarrhea_child` | integer | Q73. Number of Acute Diarrhoea |
| `information_rti` | select_one | Q74a. How much information do you know about treatment for Acute Respiratory Tra |
| `information_fever` | select_one | Q74b. How much information do you know about treatment for Acute Febrile Illness |
| `information_diarrhea` | select_one | Q74c. How much information do you know about treatment for Acute Diarrhoea (Pass |
| `drugs_aware_mgmt_Acute_Diarrhoea` | select_multiple | Q74d. Which of the following drugs are you aware for management of Acute Diarrho |
| `given_child_antibiotics` | select_one | Q74e. Have you given your child antibiotics in the last 3 months? |
| `who_prescribe_drugs` | select_one | Q74f. If yes, who prescribed the drugs? |
| `antibiotic_type_given_child` | select_multiple | Q74g. Which Antibiotics did you give your child? |
| `other_given_antibiotic_type` | text | Kindly specify any other antibiotics you give your child? |
| `drug_reaction_antibiotics` | select_one | Q74h. Has your child ever experienced reaction from taken the drug mentioned abo |
| `symptoms_antibiotics` | select_one | Q74i. If yes, which reaction did your child experienced? |
| `other_symptoms_antibiotics` | text | Kindly specify the other symptoms not on the list |
| `admitted_antibiotics` | select_one | Q74j. Was the child admitted into the hospital because of the reaction experienc |
| `symptom_disappear_antibiotics` | select_one | Q74k. Did the reaction disappear after the child stopped using the drug? |
| `another_usage_antibiotics` | select_one | Q74l. Has your child used the drug again? |
| `antimalarial` | select_one | Q75. Have you given your child antimalaria in last 3 months? |
| `who_prescribe_drugs_001` | select_one | Q75a. If yes, who prescribed the drugs? |
| `antimalarial_type` | select_multiple | Q75b. Which Antimalarial drug did you give your child? |
| `drug_reaction_antimalarial` | select_one | Q75c. Has your child ever experinced reaction from taking the drugs mentioned ab |
| `symptoms_antimalarial` | select_one | Q75d. Which of the following features was the one most severe symptom your child |
| `other_symptoms_antimalarial` | text | Kindly specify the other symptoms not on the list |
| `admitted_antimalarial` | select_one | Q75e. Was your child admitted to the hospital because of the reaction experience |
| `symptom_disappear_antimalarial` | select_one | Q75f. Did this reaction disappear after your child stopped using the drug? |
| `another_usage_antimalarial` | select_one | Q75g. Has your child use this drug again? |
| `sample_date` | date | Q76a. Date sample collected |
| `time` | time | Q76b. Time of collection |
| `sample_type` | select_multiple | Q76c. Type of sample |
| `check_mother_information` | acknowledge | ⚠️Confirm the following response Father's Name: ${father_info} Mother's Name: ${ |
| `sample_barcode_no` | barcode | Q76d. Scan the sample barcode |

</details>

### Transform
- **Household:** recodes `education_type_quranic` and `education_type_western` from 0/1 to No/Yes. `concatenated_id` = `household_uuid + "_" + index`. Flags duplicate `household_code`s.
- **Mother:** `concatenated_id` = `mother_uuid + "_" + parent_index`. Flags duplicate `mother_code`s.
- **Child:** recodes 23 split multi-select columns from 0/1 to Yes/No (Q67 feeding mode, Q74d, Q74g, Q75b, Q76c). `concatenated_id` = `_submission__uuid + "_" + _parent_index`. Flags duplicate `child_code`s.
- **Mapping CSVs:** `zamfara_household_map.csv`, `zamfara_mother_map.csv` and `zamfara_child_map.csv` rename and drop columns and set the column order.

### Push to Postgres (`sarmaan_2.sarmaan2data`)
Run order: household → mother → child. Each loader appends and skips rows whose `concatenated_id` is already in the table.

| Table | Columns referenced in code (full list = mapping CSV `db_name`) |
|---|---|
| `amr_household_information` | `start_time`, `end_time`, `enumerator_name`, `enumerator_phone_number`, `date_of_consent`, `witness_name`, `start_timme`, `state`, `lga`, `ward`, `community`, `household_consent_name`, `latitude`, `longitude`, `household_number`, `household_number2`, `household_code`, `household_name`, `household_age`, `related_to_head_household_name`, `related_to_head_household_age`, `total_no_persons_household`, `no_wives_0_59_months`, `no_children_0_59_months`, `no_children_1_59_months`, `no_children_0_28_days`, `no_wives_caregivers`, `education_type_quranic`, `education_type_western`, `phone_number`, `person_completed_household_questionnaire_signature_url`, `manifest_url`, `end_timme`, `household_uuid`, `index`, `submission_id`, `concatenated_id` |
| `amr_mother_information` | `state`, `lga`, `ward`, `community`, `cycle`, `household_code`, `mother_id`, `mother_code`, `mother_name`, `mother_age`, `mother_marital_status`, `father_name`, `no_children_less_1_month`, `no_children_1_59_month`, `mother_signature_url`, `mother_uuid`, `index`, `parent_index`, `submission_id`, `concatenated_id` (the loader drops `household_code_pull` before inserting) |
| `amr_child_information` | `id`, `state`, `lga`, `ward`, `community`, `cycle`, `household_code`, `mother_code`, `child_id`, `child_code`, `child_name`, `child_dob`, `child_age`, `child_weight`, `child_height_cm`, `father_name`, `mother_name`, `sample_date_collected`, `sample_time_collected`, `sample_barcode`, `child_uuid`, `index`, `parent_index`, `submission_id`, `concatenated_id`, plus the renamed Yes/No multi-select columns (the loader drops `household_code_pull` and `mother_code_pull`) |

---

## 2. Pharmacy

### Pull from Kobo
- **Export:** `https://kf.kobotoolbox.org/api/v2/assets/aLcuF4wGExja3LrSZxEEnB/export-settings/esoXu2auPC68oteb2G3UuGA/data.xlsx`, with labels as the column headers.
- **Sheet:** `SARMAAN II BASELINE ZAMFARA ...`, one row per pharmacy or drug shop. There are no repeat groups.

<details><summary>68 form fields (click to expand)</summary>

| Kobo field | Type | Question label |
|---|---|---|
| `starttime` | start | start |
| `endtime` | end | end |
| `start-geopoint` | start-geopoint |  |
| `deviceid` | deviceid | deviceid |
| `username` | username | Type in your Name |
| `phonenumber` | phonenumber | Phone Number |
| `concat_user` | calculate |  |
| `user_confrim` | text | confirm user and phone number |
| `concat_enu` | text | confirm enumerator and phone number |
| `enum_id` | text | Enumerator id |
| `photo_001` | image | Please take a picture of the pharmacy showing the name |
| `signed_consent` | select_one | I have read the description of the research or have had it translated into the l |
| `name_pharmacist` | text | Name of Pharmacist/Drug Store Owner |
| `consent_sign` | image | Kindly append the signature of ${name_pharmacist} here |
| `date_of_consent` | date | Date of Consent |
| `witness` | select_one | Was there a witness present? |
| `witness_name` | text | Witness Name |
| `start_time` | time | Start time |
| `states` | select_one | State |
| `lgas` | select_one | LGA |
| `ward` | select_one | Ward |
| `gps` | geopoint | Geopoint |
| `pharmacy_no` | select_one | Pharmacy Number |
| `unique` | calculate |  |
| `pharm_id` | text | Pharmacy ID is: ${unique} |
| `settlement_type` | select_one | Choose the settlement type |
| `age` | integer | Q1. Age (In years) |
| `gender` | select_one | Q2. Sex |
| `religion` | select_one | Q3. Religion |
| `other_religion` | text | Kindly specify other religion not mentioned above |
| `education` | select_one | Q4. Highest level of Education |
| `ethnicity` | select_one | Q5. Ethnicity |
| `other_ethnicity` | text | Kindly specify any other ethnicity not specified above |
| `drug_shop` | select_one | 6. Category of drug shop |
| `other_shop` | text | Kindly specify any other drug shop not specified above |
| `training` | select_one | 7. Did you receive any training on drug prescription or dispensing? |
| `training_type` | select_one | Q8. What kind of training did you receive? |
| `other_type` | text | Kindly specify any other training type not specified above |
| `experience` | integer | Q9. Number of years of experience/practice |
| `antibiotics` | select_one | Q10. Do you know what antibiotics are? |
| `antibiotic_meaning` | select_multiple | Q11. What are antibiotics? (Tick as many answers that are applicable) |
| `other_meaning` | text | Kindly specify any other meaning not specified above |
| `rational_use` | select_one | Q12. Have you been trained on rational use of antibiotics |
| `training_institute` | select_one | Q13. If you have been trained on rational use of antibiotics, please give the na |
| `other_training_institute` | text | Kindly specify any other training institute not specified above |
| `training_year` | date | Q14. When did you receive the training (Year) |
| `selling` | select_one | Q15. Do you insist on prescriptions before selling antibiotics? |
| `selling_reason` | select_multiple | Q16. If yes, please state your reason |
| `selling_reason2` | select_multiple | Q17. If no, please state your reason |
| `other_s_reason` | text | Kindly specify any other selling reason not specified above |
| `no_people` | integer | Q18. On average, how many people come to ask for antibiotics daily from your sho |
| `no_people2` | integer | Q19. On average, how many people with prescription do you sell antibiotics to wi |
| `no_people3` | integer | Q20. On average, how many people without prescription do you sell antibiotic to  |
| `no_sold` | select_one | Q21. Do you sell Less than the required number of tablets if the buyer does not  |
| `disease` | select_multiple | Q22. For which of the following suspected conditions would you give antibiotics  |
| `other_disease` | text | Kindly specify any other disease not mentioned above |
| `effectiveness` | select_one | Q23. Do you combine different antibiotics to ensure effectiveness? |
| `no_mixed` | select_one | Q24. If yes, on the average, how many different types of antibiotics will you co |
| `no_mixed2` | integer | Kindly specify the number of antibiotics mixed |
| `prevention` | select_one | Q25. Do you give your clients antibiotics for prevention infection? |
| `antibiotic_type` | select_one | Q26. If yes: Which Antibiotic, do you use most for prevention of infection? |
| `other_antibiotic_type` | text | Kindly specify any other antibiotic type you use the most |
| `injections` | select_one | Q27. Do you administer antibiotic injections? |
| `injection_type` | select_multiple | Q28. Please state name of antibiotic injection. If Yes (Tick as many as applicab |
| `other_injection_type` | text | Kindly specify any other injection type not listed above |
| `consumption_days` | integer | Q29. How many days on the average do your clients take the antibiotic injection? |
| `stock` | select_multiple | Q30. Which of these antibiotics do you have in your shop? (Please tick as many t |
| `other_stock` | text | Kindly specify any other antibiotic you have in your shop that is not listed abo |

</details>

### Transform
- **Mapping:** `zamfara_pharmacy_map.csv` (only rows with `action = keep`).
- **LGA:** numeric LGA codes from older form versions are converted to names with `zamfara_pharmacy_lga_lookup.csv`.
- **Recodes:**
  - Yes/No questions are normalised to `Yes`/`No`.
  - `settlement_type` becomes Rural/Urban, and `pharmacist_gender` becomes Male/Female.
  - Split multi-select columns change from 0/1 to No/Yes. These are the columns starting `define_antibiotics_`, `prescriptions_before_antibiotics_reason_`, `prescriptions_before_antibiotics_no_reason_`, `suspected_conditions_antibiotics_`, `administer_antibiotic_injections_name_`, `antibiotics_in_shop_`.
- **Dates:** `start_time`, `end_time`, `date_of_consent` and `training_year` are cut to `YYYY-MM-DD`.
- **Other:** `cycle` is set to the constant `"Year 1"`. `concatenated_id` = `pharmacy_uuid + "_" + index`. Duplicate `pharmacy_code`s are flagged.

### Push to Postgres (`sarmaan_2.sarmaan2data.pharmacy_information`)
Appends and skips rows whose `concatenated_id` is already in the table.

Columns referenced in code (full list = mapping CSV `db_name`): `start_time`, `end_time`, `enumerator_name`, `enumerator_phone_number`, `consent`, `witness`, `witness_name`, `date_of_consent`, `start_timme`, `state`, `lga`, `ward`, `settlement_type`, `latitude`, `longitude`, `pharmacy_number`, `pharmacy_code`, `pharmacy_photo_url`, `pharmacist_name`, `pharmacist_age`, `pharmacist_gender`, `pharmacist_signature_url`, `know_antibiotics`, `trained_antibiotics_use`, `training_year`, `experience_years`, `prescriptions_before_antibiotics`, `people_count_ask_antibitoics`, `people_count_sell_antibitoics_with_prescription`, `people_count_sell_antibitoics_no_prescription`, `sell_less_than_required_antibiotics`, `combine_antibiotics`, `combine_antibiotics_count`, `antibiotics_prevent_infection`, `administer_antibiotic_injections`, `days_antibiotics_injection`, `cycle`, `pharmacy_uuid`, `index`, `submission_id`, `concatenated_id`, plus the `define_antibiotics_*`, `prescriptions_before_antibiotics_reason_*`, `prescriptions_before_antibiotics_no_reason_*`, `suspected_conditions_antibiotics_*`, `administer_antibiotic_injections_name_*`, `antibiotics_in_shop_*` columns.

---

## 3. Mortality

### Pull from Kobo
- **Source:** a **local file** (`MORTALITY_DIR/kobo_exports/mortality_export.xlsx`, or a path given on the command line). The Mortality stager doesn't call the Kobo API. Switching it over is tracked in GDI-1217.

| Export sheet | Rows | Kobo columns read directly by code |
|---|---|---|
| First sheet (form title) | One per household | `_uuid`, `_index`, `_id`, `hh_category`, LGA from `lgas`/`lga_confirm`/`lgas_k`, ward from `ward`/`wards`/`ward_confirm`, community from `community_confirm`/`community_name`/`check_hh` (first non-blank wins) |
| `female` | One per woman | `_submission__uuid`, `_parent_index`, `_index`, `_submission__id` |
| `pregnancy_history` | One per pregnancy | `_submission__uuid`, `_parent_index`, `_index`, `_submission__id` |

- **Other columns:** everything else is mapped by `mapping/household_map.csv`, `female_map.csv` and `pregnancy_map.csv`. These have the columns `kobo_name`, `db_name`, `action` (keep/review/drop) and `transform`.
- **Available transforms:** `none`, `int_cast`, `strip_leading_zero`, `binary_yesno`, `yesno_titlecase`, `simple_capitalize`, `date_truncate`, `datetime_full_utc`, `datetime_short_tz`, `submission_time_utc`, `underscore_to_space`, `hh_category_range`, `int_cast_dk99`, `label_recode:<name>`.

### Transform
- **Location:** `state` falls back to `"Yobe"` when blank. Female and pregnancy rows get `state`, `lga`, `ward` and `community` from the household via `household_code`.
- **`concatenated_id`:** household = `household_uuid + "_" + index`; female = `female_uuid + "_" + parent_index`; pregnancy = `pregnancy_uuid + "_" + parent_index`.
- **Checks:** flags duplicate `household_code`, household `concatenated_id` and `pregnancy_code` values, plus orphan female and pregnancy rows with no matching household.

### Push to Postgres (`mortality.mortalitydata`)
One staging workbook with sheets `household`, `female` and `pregnancy`, loaded in that order. Rows are skipped when their `concatenated_id` is already present. The column lists below are exact and in the order they're loaded.

**`household_mortality`** (83 columns)

`start_time`, `end_time`, `enumerator_name`, `enumerator_phone_number`, `enum_id`, `consent`, `household_head_consent`, `household_consent_name`, `date_of_consent`, `witness`, `witness_name`, `start_timme`, `state`, `lga`, `ward`, `community`, `settlement_cluster`, `women_15_49`, `latitude`, `longitude`, `household_no_category`, `household_number`, `household_code`, `cycle`, `settlement_type`, `language_communication`, `other_language_communication`, `household_status`, `head_household`, `household_name`, `gender_head_household`, `household_age`, `related_to_head_household_name`, `related_to_head_household_live`, `related_to_head_household_stay`, `related_to_head_household_age`, `related_to_head_household_gender`, `related_to_head_household`, `related_to_head_household_others`, `education`, `education_type_quranic`, `education_type_western`, `school_level`, `school_level_primary`, `school_level_secondary`, `own_mobile_phone`, `smart_mobile_phone`, `respondent_phone_number`, `television`, `electric_iron`, `fan`, `refrigerator`, `electricity`, `generator`, `bank_account`, `watch`, `floor_material`, `floor_material_others`, `cooking_stove`, `cooking_stove_others`, `drinking_water_source`, `drinking_water_source_others`, `cooking_water_source`, `cooking_water_source_others`, `no_sleeping_rooms`, `toilet_facility_type`, `toilet_facility_type_others`, `shared_toilet_facility`, `toilet_facility_location`, `waste_disposal`, `waste_disposal_others`, `household_handwash_use`, `household_handwash_use_others`, `household_handwash_observed`, `total_no_persons_household`, `current_women_10_55`, `end_timme`, `audio`, `audio_url`, `household_uuid`, `index`, `submission_id`, `concatenated_id`

**`females_mortality`** (51 columns)

`state`, `lga`, `ward`, `community`, `household_code`, `female_id`, `mother_code`, `female_name`, `birth_year`, `birth_month`, `female_age`, `female_dob`, `education`, `school_level_quranic`, `school_level_western`, `school_level_cat`, `school_level_attained_primary_secondary`, `school_level_attained_higher`, `birthing_status`, `children_living_together`, `sons_living_together`, `daughters_living_together`, `children_living_elsewhere`, `sons_living_elsewhere`, `daughters_living_elsewhere`, `children_alive_later_died`, `boys_alive_later_died`, `girls_alive_later_died`, `sum_children_alive`, `sum_children_dead`, `sum_alive_dead_children`, `confirm_birthing_no`, `miscarriage_abortion_pregnancy`, `miscarriage_abortion_count`, `miscarriage_count`, `total_pregnancies`, `pregnancy_id`, `agg_child_still_alive`, `agg_child_alive_death`, `agg_dead_miscarrage`, `pregnancy_status`, `pregnancy_report`, `pregnancy_length_weeks`, `pregnancy_length_months`, `pregnancy_decision`, `future_pregnancies`, `female_uuid`, `parent_index`, `index`, `submission_id`, `concatenated_id`

**`pregnancy_mortality`** (70 columns)

`state`, `lga`, `ward`, `community`, `household_code`, `mother_code`, `pregnancy_id`, `pregnancy_code`, `pregnancy_form`, `birth_form`, `birth_status`, `child_alive_name`, `child_alive_gender`, `child_alive_later_died_gender`, `child_age_category`, `child_month_less_1_month`, `child_day_less_1_month`, `child_dob_less_1_month`, `child_year_alive_later_died`, `child_month_alive_later_died`, `child_day_alive_later_died`, `child_dob_alive_later_died`, `child_year_1_11_month`, `child_month_1_11_month`, `child_day_1_11_month`, `child_dob_1_11_month`, `child_year_12_59_month`, `child_month_12_59_month`, `child_day_12_59_month`, `child_dob_12_59_month`, `child_year_greater_5_years`, `child_month_greater_5_years`, `child_day_greater_5_years`, `year_pregnancy_ended`, `month_pregnancy_ended`, `day_pregnancy_ended`, `pregnancy_report`, `miscarriage_pregnancy_report`, `pregnancy_report_length_weeks`, `pregnancy_report_length_months`, `miscarriage_pregnancy_length_weeks`, `miscarriage_pregnancy_length_months`, `child_age_less_1_month`, `child_age_less_1_11_month`, `child_age_less_12_59_month`, `child_age_greater_5_years`, `child_still_alive`, `child_age_1_11_last_birthday`, `child_age_1_to_more_than_5_years_last_birthday`, `child_age_alive_later_died_category`, `child_age_months_alive_later_died`, `child_age_alive_later_died_less_1_month`, `child_age_days_alive_later_died`, `first_birthday`, `child_age_alive_later_died_less_1_year`, `child_age_alive_later_died_1_less_month`, `child_age_alive_later_died_greater_1_year`, `child_age_alive_later_died_less_2_year`, `child_living_together`, `child_vaccinated`, `child_ever_vaccinated`, `child_alive_still`, `child_alive_death`, `birth_form_dead`, `birth_form_miscarriage`, `index`, `parent_index`, `pregnancy_uuid`, `submission_id`, `concatenated_id`
