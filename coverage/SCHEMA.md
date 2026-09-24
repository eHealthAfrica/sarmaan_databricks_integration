# SARMAAN Coverage pipeline: data schema

What the Coverage pipeline reads from KoboToolbox and what it writes to the eHA Postgres database.

- **Kobo form:** SARMAAN II C2 BAUCHI COVERAGE EVALUATION LIVE FORM. The form ID and export settings ID are set in `.env` (`KOBO_ASSET_UID`, `KOBO_EXPORT_SETTINGS_ID`).
- **Export:** Excel with XML headers (field names, not labels), one sheet per repeat group.
- **Mappings:** everything below is generated from `mappings/step_1_map_file.xlsx`, `step_2_map_file.xlsx` and `step_5_map_file.xlsx`, and from the live Kobo form. Editing those files changes the schema with no code changes.

## Flow

```
Kobo export (XML headers)
  └─ preprocessor: drop 'Unnamed' columns, split child_names11 → child_names11 + agee_eligible,
                   decode states/lgas/wards/community_name codes → names (mappings/dat.csv)
       ├─ Step 1 (step_1_map) ── all submissions, all TEXT ──────────────► raw_data.coverage_*
       └─ Step 2 (step_2_map) rename ─► Step 5 (step_5_map) approved only,
                                        typed, 0/1 → no/yes ─────────────► sarmaan2data.coverage_*
          Step 3 (step_3_map) partner workbook, Step 4 validation (does not write to the DB)
```

- **Raw load:** every submission, approved or not. Columns are stored as `TEXT`.
- **Clean load:** only submissions with `_validation_status = validation_status_approved` (and children whose household is approved). Columns are typed as in `step_5_map` `data_type`.
- **Both loads:** upsert on the primary key. Existing tables are never altered: a mapped column missing from the table stops the run. Everything runs in one transaction.

## Tables

| Kobo sheet | Raw table (`raw_data`) | Clean table (`sarmaan2data`) |
|---|---|---|
| main sheet (form title) | `coverage_household` | `coverage_household` |
| `child_info` repeat | `coverage_all_children` | `coverage_all_children` |
| `net_repeat` repeat | `coverage_net_info` | `coverage_net_info` |
| `child_infoo` repeat | `coverage_children_1_59` | `coverage_children_1_59` |

The `g_polygon_ward` / `g_polygon_ward2` repeats in the form are not loaded.

## Keys

| Table | Raw PK | Raw FK | Clean PK | Clean FK |
|---|---|---|---|---|
| Household | `index_uuid` | - | `concatenated_id` | - |
| All children | `child_id_submission__uuid` | `_parent_index_submission__uuid` → coverage_household.index_uuid | `child_id_childd_uuid` | `concatenated_id` → coverage_household.concatenated_id |
| Nets | `net_id_submission__uuid` | `_parent_index_submission__uuid` → coverage_household.index_uuid | `net_id_net_uuid` | `concatenated_id` → coverage_household.concatenated_id |
| Children 1–59 months | `child_idd_submission__uuid` | `_parent_index_submission__uuid` → coverage_household.index_uuid | `child_id_child_uuid` | `concatenated_id` → coverage_household.concatenated_id |

- **Raw keys:** plain concatenation, no separator (for example `_index` + `_uuid`).
- **Clean `concatenated_id`:** household = `uuid + "_" + index`; child tables = `uuid + "_" + <household's index>`, looked up through the household's `uuid`. A child row with no matching household is rejected in step 6.

---

## Household

**Kobo sheet:** main sheet (form title)

### Kobo → `raw_data.coverage_household` (311 columns, all TEXT)

<details><summary>Show columns</summary>

| Kobo column | Kobo type | Raw DB column |
|---|---|---|
| `starttime` | start | `starttime` |
| `endtime` | end | `endtime` |
| `deviceid` | deviceid | `deviceid` |
| `username` | username | `username` |
| `phonenumber` | phonenumber | `phonenumber` |
| `start-geopoint` | start-geopoint | `start_geopoint` |
| `_start-geopoint_latitude` | Kobo system | `start_geopoint_latitude` |
| `_start-geopoint_longitude` | Kobo system | `start_geopoint_longitude` |
| `_start-geopoint_altitude` | Kobo system | `start_geopoint_altitude` |
| `_start-geopoint_precision` | Kobo system | `start_geopoint_precision` |
| `concat_user` | calculate | `concat_user` |
| `note_missing_username` | note | `note_missing_username` |
| `note_missing_phone_number` | note | `note_missing_phone_number` |
| `note_incorrect_date_and_time` | note | `note_incorrect_date_and_time` |
| `user_confrim` | text | `user_confrim` |
| `concat_enu` | text | `concat_enu` |
| `enum_id` | text | `enum_id` |
| `wrong_login` | note | `wrong_login` |
| `note1` | note | `note1` |
| `note2` | note | `note2` |
| `signed_consent` | select_one | `signed_consent` |
| `no_consent_reason` | select_one | `no_consent_reason` |
| `other_no_consent_reason` | text | `other_no_consent_reason` |
| `note3` | note | `note3` |
| `no_under_18` | derived by Kobo export / preprocessor | `no_under_18` |
| `no_eligible_children` | integer | `no_eligible_children` |
| `total_eligible` | calculate | `total_eligible` |
| `no_eligible` | note | `no_eligible` |
| `states` | select_one | `states` |
| `lgas` | select_one_from_file | `lgas` |
| `wards` | select_one_from_file | `wards` |
| `community_name` | select_one_from_file | `community_name` |
| `settlement_type` | select_one | `settlement_type` |
| `lga_confirm` | text | `lga_confirm` |
| `ward_confirm` | text | `ward_confirm` |
| `community_confirm` | text | `community_confirm` |
| `hh_category` | select_one | `hh_category` |
| `household_no1` | select_one | `household_no1` |
| `household_no2` | select_one | `household_no2` |
| `unique` | calculate | `unique` |
| `visit_date` | date | `visit_date` |
| `formatted_date` | calculate | `formatted_date` |
| `unique_code` | calculate | `unique_code` |
| `hh_id` | text | `hh_id` |
| `gps_location` | geopoint | `gps_location` |
| `_gps_location_latitude` | Kobo system | `gps_location_latitude` |
| `_gps_location_longitude` | Kobo system | `gps_location_longitude` |
| `_gps_location_altitude` | Kobo system | `gps_location_altitude` |
| `_gps_location_precision` | Kobo system | `gps_location_precision` |
| `check_location` | acknowledge | `check_location` |
| `household_head` | select_one | `household_head` |
| `household_headname` | text | `household_headname` |
| `gender_hh` | select_one | `gender_hh` |
| `age_hhead` | integer | `age_hhead` |
| `name_questionnaire` | text | `name_questionnaire` |
| `live_here` | select_one | `live_here` |
| `stay_last_night` | select_one | `stay_last_night` |
| `age_hhhead` | integer | `age_hhhead` |
| `gender_phh` | select_one | `gender_phh` |
| `household_relationship` | select_one | `household_relationship` |
| `other_household_relationship` | text | `other_household_relationship` |
| `phoneno` | text | `phoneno` |
| `hh_education_level` | select_one | `hh_education_level` |
| `hh_occupation` | select_one | `hh_occupation` |
| `duration_of_stay` | integer | `duration_of_stay` |
| `own_household` | select_one | `own_household` |
| `electricity` | select_one | `electricity` |
| `radio` | select_one | `radio` |
| `television` | select_one | `television` |
| `a_non_mobile_telephone` | select_one | `a_non_mobile_telephone` |
| `computer` | select_one | `computer` |
| `refrigerator` | select_one | `refrigerator` |
| `chair` | select_one | `chair` |
| `bed` | select_one | `bed` |
| `sofa` | select_one | `sofa` |
| `cupboard` | select_one | `cupboard` |
| `animal_drawn_cart` | select_one | `animal_drawn_cart` |
| `bicycle` | select_one | `bicycle` |
| `motorcycle_or_motor_scooter` | select_one | `motorcycle_or_motor_scooter` |
| `car_or_truck` | select_one | `car_or_truck` |
| `boat_with_motor` | select_one | `boat_with_motor` |
| `canoe` | select_one | `canoe` |
| `keke_napep` | select_one | `keke_napep` |
| `fan` | select_one | `fan` |
| `watch` | select_one | `watch` |
| `mobile_telephone` | select_one | `mobile_telephone` |
| `table` | select_one | `table` |
| `electric_iron` | select_one | `electric_iron` |
| `bank_account` | select_one | `bank_account` |
| `air_condition` | select_one | `air_condition` |
| `generator` | select_one | `generator` |
| `water_source` | select_one | `water_source` |
| `other_water_source` | text | `other_water_source` |
| `water_source2` | select_one | `water_source2` |
| `other_water_source2` | text | `other_water_source2` |
| `water_location` | select_one | `water_location` |
| `source_water_min` | integer | `source_water_min` |
| `m_source` | select_one | `m_source` |
| `constant_flow` | select_one | `constant_flow` |
| `safe_consumption` | select_one | `safe_consumption` |
| `water_treatment` | select_multiple | `water_treatment` |
| `water_treatment/boil` | select_multiple | `water_treatment_boil` |
| `water_treatment/add_bleach_chlorine` | select_multiple | `water_treatment_add_bleach_chlorine` |
| `water_treatment/strain_through_a_cloth` | select_multiple | `water_treatment_strain_through_a_cloth` |
| `water_treatment/use_water_filter` | select_multiple | `water_treatment_use_water_filter` |
| `water_treatment/solar_disinfection` | select_multiple | `water_treatment_solar_disinfection` |
| `water_treatment/let_it_stand_and_settle` | select_multiple | `water_treatment_let_it_stand_and_settle` |
| `water_treatment/alum` | select_multiple | `water_treatment_alum` |
| `water_treatment/other` | select_multiple | `water_treatment_other` |
| `water_treatment/don't_know` | select_multiple | `water_treatment_dont_know` |
| `other_water` | text | `other_water` |
| `housing` | select_one | `housing` |
| `floor_material` | select_one | `floor_material` |
| `other_floor_material` | text | `other_floor_material` |
| `roof_material` | select_one | `roof_material` |
| `other_roof_material` | text | `other_roof_material` |
| `wall_material` | select_one | `wall_material` |
| `other_wall_material` | text | `other_wall_material` |
| `toilet_facility` | select_one | `toilet_facility` |
| `other_toilet_facility` | text | `other_toilet_facility` |
| `shared_toilet` | select_one | `shared_toilet` |
| `no_use_toilet` | integer | `no_use_toilet` |
| `toilet_location` | select_one | `toilet_location` |
| `energy_source` | select_one | `energy_source` |
| `other_energy_source` | text | `other_energy_source` |
| `cooking_location` | select_one | `cooking_location` |
| `other_cooking_location` | text | `other_cooking_location` |
| `separate_location` | select_one | `separate_location` |
| `live_stock` | select_one | `live_stock` |
| `livestock_owned` | select_multiple | `livestock_owned` |
| `livestock_owned/milk_cows_or_bulls` | select_multiple | `livestock_owned_milk_cows_or_bulls` |
| `livestock_owned/horses_donkeys_or_mules` | select_multiple | `livestock_owned_horses_donkeys_or_mules` |
| `livestock_owned/goats` | select_multiple | `livestock_owned_goats` |
| `livestock_owned/sheep` | select_multiple | `livestock_owned_sheep` |
| `livestock_owned/chickens_or_other_poultry` | select_multiple | `livestock_owned_chickens_or_other_poultry` |
| `livestock_owned/pigs` | select_multiple | `livestock_owned_pigs` |
| `livestock_owned/camels` | select_multiple | `livestock_owned_camels` |
| `livestock_owned/other` | select_multiple | `livestock_owned_other` |
| `other_livestock` | text | `other_livestock` |
| `land` | select_one | `land` |
| `land_type` | select_multiple | `land_type` |
| `land_type/plot` | select_multiple | `land_type_plot` |
| `land_type/acres` | select_multiple | `land_type_acres` |
| `land_type/hectares` | select_multiple | `land_type_hectares` |
| `land_quantity` | integer | `land_quantity` |
| `land_quantity1` | integer | `land_quantity1` |
| `land_quantity2` | integer | `land_quantity2` |
| `note1_001` | note | `note1_001` |
| `washing_hand` | select_one | `washing_hand` |
| `water_avail` | select_one | `water_avail` |
| `soap_avail` | select_multiple | `soap_avail` |
| `soap_avail/soap` | select_multiple | `soap_avail_soap` |
| `soap_avail/ash_mud` | select_multiple | `soap_avail_ash_mud` |
| `soap_avail/none_of_these_present` | select_multiple | `soap_avail_none_of_these_present` |
| `shower_place` | select_one | `shower_place` |
| `water_avail_there` | select_one | `water_avail_there` |
| `bedroom` | integer | `bedroom` |
| `bedroom_used` | integer | `bedroom_used` |
| `no_bedroom` | integer | `no_bedroom` |
| `number_nets` | select_one | `number_nets` |
| `mosquito_net` | integer | `mosquito_net` |
| `mda1` | select_one | `mda1` |
| `mda_other_visit` | derived by Kobo export / preprocessor | `mda_other_visit` |
| `mda_reason` | select_multiple | `mda_reason` |
| `mda_reason/it_prevents_child_death` | select_multiple | `mda_reason_it_prevents_child_death` |
| `mda_reason/it_improves_child_health` | select_multiple | `mda_reason_it_improves_child_health` |
| `mda_reason/it_is_part_of_a_research_study` | select_multiple | `mda_reason_it_is_part_of_a_research_study` |
| `mda_reason/the_health_worker_did_not_explain_why_they_were_offering_this_drug` | select_multiple | `mda_reason_the_health_worker_did_not_explain_why_they_were_offe` |
| `mda_reason/don’t_know` | select_multiple | `mda_reason_dont_know` |
| `mda_reason/other` | select_multiple | `mda_reason_other` |
| `mda_reasons` | text | `mda_reasons` |
| `e_children` | text | `e_children` |
| `time_spent` | integer | `time_spent` |
| `azt_knowledge` | select_one | `azt_knowledge` |
| `how_aztknowledge` | select_multiple | `how_aztknowledge` |
| `how_aztknowledge/sarmaan_poster_in_the_village` | select_multiple | `how_aztknowledge_sarmaan_poster_in_the_village` |
| `how_aztknowledge/town_criers` | select_multiple | `how_aztknowledge_town_criers` |
| `how_aztknowledge/radio_jingles` | select_multiple | `how_aztknowledge_radio_jingles` |
| `how_aztknowledge/don't_know_cannot_recall` | select_multiple | `how_aztknowledge_dont_know_cannot_recall` |
| `how_aztknowledge/family_member_friend_neighbor` | select_multiple | `how_aztknowledge_family_member_friend_neighbor` |
| `how_aztknowledge/professional_health_staff` | select_multiple | `how_aztknowledge_professional_health_staff` |
| `how_aztknowledge/community_drug_distributor_community_health_worker_teacher` | select_multiple | `how_aztknowledge_community_drug_distributor_community_health_wo` |
| `how_aztknowledge/community_or_religious_leader` | select_multiple | `how_aztknowledge_community_or_religious_leader` |
| `how_aztknowledge/brochuresflyers` | select_multiple | `how_aztknowledge_brochuresflyers` |
| `how_aztknowledge/banners` | select_multiple | `how_aztknowledge_banners` |
| `how_aztknowledge/radio` | select_multiple | `how_aztknowledge_radio` |
| `how_aztknowledge/tv` | select_multiple | `how_aztknowledge_tv` |
| `how_aztknowledge/social_media` | select_multiple | `how_aztknowledge_social_media` |
| `how_aztknowledge/refused_to_answer` | select_multiple | `how_aztknowledge_refused_to_answer` |
| `how_aztknowledge/other` | select_multiple | `how_aztknowledge_other` |
| `other_howazt` | text | `other_howazt` |
| `c_offer` | select_one | `c_offer` |
| `participation_reason` | select_multiple | `participation_reason` |
| `participation_reason/c_leader` | select_multiple | `participation_reason_c_leader` |
| `participation_reason/imam` | select_multiple | `participation_reason_imam` |
| `participation_reason/h_worker` | select_multiple | `participation_reason_h_worker` |
| `participation_reason/c_sick` | select_multiple | `participation_reason_c_sick` |
| `participation_reason/p_study` | select_multiple | `participation_reason_p_study` |
| `participation_reason/c_healthy` | select_multiple | `participation_reason_c_healthy` |
| `participation_reason/no_reason` | select_multiple | `participation_reason_no_reason` |
| `participation_reason/e_taking_it` | select_multiple | `participation_reason_e_taking_it` |
| `participation_reason/r_answer` | select_multiple | `participation_reason_r_answer` |
| `participation_reason/other` | select_multiple | `participation_reason_other` |
| `other_participation` | text | `other_participation` |
| `c_necessary` | select_one | `c_necessary` |
| `why_necessary` | select_multiple | `why_necessary` |
| `why_necessary/prevention_of_trachoma` | select_multiple | `why_necessary_prevention_of_trachoma` |
| `why_necessary/prevention_of_guineaworm` | select_multiple | `why_necessary_prevention_of_guineaworm` |
| `why_necessary/prevention_of_onchocerciasis` | select_multiple | `why_necessary_prevention_of_onchocerciasis` |
| `why_necessary/prevention_of_polio` | select_multiple | `why_necessary_prevention_of_polio` |
| `why_necessary/prevention_of_malaria` | select_multiple | `why_necessary_prevention_of_malaria` |
| `why_necessary/prevention_of_diarrhoea` | select_multiple | `why_necessary_prevention_of_diarrhoea` |
| `why_necessary/prevention_of_respiratory_tract_infection` | select_multiple | `why_necessary_prevention_of_respiratory_tract_infection` |
| `why_necessary/prevention_of_febrile_illness` | select_multiple | `why_necessary_prevention_of_febrile_illness` |
| `why_necessary/prevention_of_diseases_that_can_be_avoided_by_vaccines` | select_multiple | `why_necessary_prevention_of_diseases_that_can_be_avoided_by_vac` |
| `why_necessary/prevention_of_death` | select_multiple | `why_necessary_prevention_of_death` |
| `why_necessary/don’t_know` | select_multiple | `why_necessary_dont_know` |
| `why_necessary/other` | select_multiple | `why_necessary_other` |
| `other_why` | text | `other_why` |
| `thoughts_treatment` | select_multiple | `thoughts_treatment` |
| `thoughts_treatment/house_to_house_treatment_makes_it_easy` | select_multiple | `thoughts_treatment_house_to_house_treatment_makes_it_easy` |
| `thoughts_treatment/trusted_distributors_cdds_from_the_community` | select_multiple | `thoughts_treatment_trusted_distributors_cdds_from_the_community` |
| `thoughts_treatment/no_long_wait_for_drugs` | select_multiple | `thoughts_treatment_no_long_wait_for_drugs` |
| `thoughts_treatment/free_drugs` | select_multiple | `thoughts_treatment_free_drugs` |
| `thoughts_treatment/no_specific_part_i_liked` | select_multiple | `thoughts_treatment_no_specific_part_i_liked` |
| `thoughts_treatment/refused_to_answer` | select_multiple | `thoughts_treatment_refused_to_answer` |
| `thoughts_treatment/other` | select_multiple | `thoughts_treatment_other` |
| `other_thoughts` | text | `other_thoughts` |
| `thoughts_treatment2` | select_multiple | `thoughts_treatment2` |
| `thoughts_treatment2/inconvenient_time` | select_multiple | `thoughts_treatment2_inconvenient_time` |
| `thoughts_treatment2/unfriendly_distributors_cdds` | select_multiple | `thoughts_treatment2_unfriendly_distributors_cdds` |
| `thoughts_treatment2/drugs_were_not_available_or_got_finished` | select_multiple | `thoughts_treatment2_drugs_were_not_available_or_got_finished` |
| `thoughts_treatment2/long_duration_of_time` | select_multiple | `thoughts_treatment2_long_duration_of_time` |
| `thoughts_treatment2/adverse_drug_reaction` | select_multiple | `thoughts_treatment2_adverse_drug_reaction` |
| `thoughts_treatment2/did_not_give_treatment_for_other_diseases` | select_multiple | `thoughts_treatment2_did_not_give_treatment_for_other_diseases` |
| `thoughts_treatment2/refused_to_answer` | select_multiple | `thoughts_treatment2_refused_to_answer` |
| `thoughts_treatment2/other` | select_multiple | `thoughts_treatment2_other` |
| `other_thoughts2` | text | `other_thoughts2` |
| `challenge_azt` | select_multiple | `challenge_azt` |
| `challenge_azt/financial_constraints` | select_multiple | `challenge_azt_financial_constraints` |
| `challenge_azt/lack_of_transportation` | select_multiple | `challenge_azt_lack_of_transportation` |
| `challenge_azt/lack_of_awareness` | select_multiple | `challenge_azt_lack_of_awareness` |
| `challenge_azt/cultural_beliefs` | select_multiple | `challenge_azt_cultural_beliefs` |
| `challenge_azt/others` | select_multiple | `challenge_azt_others` |
| `challenge_azt/none` | select_multiple | `challenge_azt_none` |
| `other_challenge` | text | `other_challenge` |
| `drugs_again` | select_one | `drugs_again` |
| `drugss_again` | select_multiple | `drugss_again` |
| `drugss_again/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | select_multiple | `drugss_again_afraid_of_side_effects_or_experienced_adverse_drug` |
| `drugss_again/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | select_multiple | `drugss_again_parent_caregiver_beleve_the_child_is_not_at_risk_f` |
| `drugss_again/medicine_doesn’t_work` | select_multiple | `drugss_again_medicine_doesnt_work` |
| `drugss_again/negative_experience_with_distributors_cdds` | select_multiple | `drugss_again_negative_experience_with_distributors_cdds` |
| `drugss_again/refused_to_answer` | select_multiple | `drugss_again_refused_to_answer` |
| `drugss_again/other` | select_multiple | `drugss_again_other` |
| `drugggs_again` | select_one | `drugggs_again` |
| `next_time` | select_one | `next_time` |
| `other_time` | text | `other_time` |
| `change` | select_one | `change` |
| `note7` | note | `note7` |
| `note8` | note | `note8` |
| `ac_module` | select_one | `ac_module` |
| `info1` | select_one | `info1` |
| `info2` | select_one | `info2` |
| `info3` | select_one | `info3` |
| `info4` | select_one | `info4` |
| `info5` | select_one | `info5` |
| `info6` | select_one | `info6` |
| `info7` | select_one | `info7` |
| `notezz` | note | `notezz` |
| `info8` | select_one | `info8` |
| `info9` | select_one | `info9` |
| `note1p` | note | `note1p` |
| `willingness` | integer | `willingness` |
| `min_amount` | integer | `min_amount` |
| `max_amount` | integer | `max_amount` |
| `willingness1` | select_multiple | `willingness1` |
| `willingness1/it_will_help_my_child_from_falling_ill` | select_multiple | `willingness1_it_will_help_my_child_from_falling_ill` |
| `willingness1/it_will_help_prevent_my_child_from_dying` | select_multiple | `willingness1_it_will_help_prevent_my_child_from_dying` |
| `willingness1/it_will_aid_the_growth_of_my_child` | select_multiple | `willingness1_it_will_aid_the_growth_of_my_child` |
| `willingness1/it_would_be_cheaper_i_have_the_money` | select_multiple | `willingness1_it_would_be_cheaper_i_have_the_money` |
| `willingness1/other` | select_multiple | `willingness1_other` |
| `willingness1/don’t_know` | select_multiple | `willingness1_dont_know` |
| `other_willingness1` | text | `other_willingness1` |
| `willingness3` | select_multiple | `willingness3` |
| `willingness3/it_has_no_benefit_to_my_child's_health` | select_multiple | `willingness3_it_has_no_benefit_to_my_child_s_health` |
| `willingness3/don’t_have_the_money` | select_multiple | `willingness3_don_t_have_the_money` |
| `willingness3/government_should_continue_to_make_it_free` | select_multiple | `willingness3_government_should_continue_to_make_it_free` |
| `willingness3/don’t_know` | select_multiple | `willingness3_dont_know` |
| `willingness3/other` | select_multiple | `willingness3_other` |
| `other_willingness3` | text | `other_willingness3` |
| `info_x` | select_one | `info_x` |
| `info_y` | select_one | `info_y` |
| `info_q` | select_one | `info_q` |
| `info11` | integer | `info11` |
| `info12` | integer | `info12` |
| `info13` | integer | `info13` |
| `info14` | integer | `info14` |
| `timespent` | calculate | `timespent` |
| `comment_end` | derived by Kobo export / preprocessor | `comment_end` |
| `_id` | Kobo system | `id` |
| `_uuid` | Kobo system | `uuid` |
| `_submission_time` | Kobo system | `submission_time` |
| `_validation_status` | Kobo system | `validation_status` |
| `_notes` | Kobo system | `notes` |
| `_status` | Kobo system | `status` |
| `_submitted_by` | Kobo system | `submitted_by` |
| `__version__` | Kobo system | `version` |
| `_tags` | Kobo system | `tags` |
| `meta/rootUuid` | Kobo system | `meta_rootuuid` |
| `_index` | Kobo system | `index` |
| `index_uuid` | computed | `index_uuid` |

</details>

### Kobo → `sarmaan2data.coverage_household` (265 columns)

<details><summary>Show columns</summary>

| Kobo column | After step 2 | Clean DB column | Postgres type |
|---|---|---|---|
| `starttime` | `start` | `start` | timestamp without time zone |
| `endtime` | `end` | `end` | timestamp without time zone |
| `username` | `username` | `enumerator_name` | character varying(60) |
| `phonenumber` | `phonenumber` | `enumerator_phone_number` | character varying(15) |
| `enum_id` | `Data_Collector_id` | `enum_id` | smallint |
| `signed_consent` | `consent` | `consent` | consent_enum |
| `no_consent_reason` | `noconsent_reasons` | `noconsent_reasons` | character varying |
| `other_no_consent_reason` | `othernoconsent_reasons` | `othernoconsent_reasons` | character varying |
| `no_under_18` | `num_of_Childrenhh` | `num_of_childrenhh` | smallint |
| `no_eligible_children` | `S2_num_children1-59` | `num_children1_59` | smallint |
| `total_eligible` | `total_eligible` | `total_eligible` | smallint |
| `no_eligible` | `no_eligible` | `no_eligible` | smallint |
| `states` | `q1_States` | `state` | character varying(20) |
| `lgas` | `q2_LGAs` | `lga` | character varying(40) |
| `wards` | `q3_Wards` | `ward` | character varying(50) |
| `community_name` | `q4_Community` | `community` | character varying(100) |
| `settlement_type` | `q5_Settlement_type` | `settlement_type` | settlement_type_enum |
| computed from `unique_code` prefix (B/C1 → Baseline, C2 → Second, C3 → Third, C4 → Fourth) | `cycle` | `cycle` | character varying(10) |
| `unique` | `q6_HH_number` | `household_no` | character varying(3) |
| `visit_date` | `q8_Interview_date` | `formatted_date` | date |
| `unique_code` | `unique_code` | `household_code` | character varying(20) |
| `_gps_location_latitude` | `q9_GPS_Latitude` | `latitude` | double precision |
| `_gps_location_longitude` | `q9_GPS_Longitude` | `longitude` | double precision |
| `household_head` | `q10_Head_of_HH` | `head_household` | character varying(4) |
| `household_headname` | `q11_h_head_name` | `household_name` | character varying(60) |
| `gender_hh` | `q12_Gender_ofh_head` | `gender_head_household` | gender_enum |
| `age_hhead` | `q13_Age_ofh_head` | `household_age` | smallint |
| `name_questionnaire` | `q14_name_of_proxy` | `related_to_head_household_name` | character varying(60) |
| `live_here` | `q15_living_status` | `related_to_head_household_live` | character varying(4) |
| `stay_last_night` | `q16_stay_lastnight` | `related_to_head_household_stay` | character varying(4) |
| `age_hhhead` | `q17_Age_proxy` | `related_to_head_household_age` | smallint |
| `gender_phh` | `q18_gender_proxy` | `related_to_head_household_gender` | gender_enum |
| `household_relationship` | `q19_Relashipwith_Head` | `related_to_head_household` | character varying |
| `other_household_relationship` | `q19a_otherRelaship` | `related_to_head_household_others` | character varying |
| `phoneno` | `phone_no` | `hh_phoneno` | bigint |
| `hh_education_level` | `q20_Edu_level` | `school_level` | character varying(20) |
| `hh_occupation` | `q21_Occupation` | `occupation` | character varying(60) |
| `duration_of_stay` | `q22_years_lived_incomm` | `continuously_living` | smallint |
| `electricity` | `q23_has_electricity` | `electricity` | yes_no_enum |
| `radio` | `q24_own_radio` | `radio` | yes_no_enum |
| `television` | `q25_own_television` | `television` | yes_no_enum |
| `a_non_mobile_telephone` | `q26_own_anonmobiletelephone` | `land_telephone` | yes_no_enum |
| `computer` | `q27_own_computer` | `computer` | yes_no_enum |
| `refrigerator` | `q28_own_refrigerator` | `refrigerator` | yes_no_enum |
| `chair` | `q29_own_chair` | `chair` | yes_no_enum |
| `bed` | `q30_own_bed` | `bed` | yes_no_enum |
| `sofa` | `q31_own_sofa` | `sofa` | yes_no_enum |
| `cupboard` | `q32_own_cupboard` | `cupboard` | yes_no_enum |
| `animal_drawn_cart` | `q33_own_animaldrawncart` | `cart` | yes_no_enum |
| `bicycle` | `q34_own_bicycle` | `bicycle` | yes_no_enum |
| `motorcycle_or_motor_scooter` | `q35_own_motorcycmotscoot` | `motorcycle` | yes_no_enum |
| `car_or_truck` | `q36_own_carortruck` | `car` | yes_no_enum |
| `boat_with_motor` | `q37_own_boatwithmotor` | `boat` | yes_no_enum |
| `canoe` | `q38_own_canoe` | `canoe` | yes_no_enum |
| `keke_napep` | `q39_own_kekenapep` | `keke` | yes_no_enum |
| `fan` | `q40_own_fan` | `fan` | yes_no_enum |
| `watch` | `q41_own_watch` | `watch` | yes_no_enum |
| `mobile_telephone` | `q42_own_mobilephone` | `mobile_telephone` | yes_no_enum |
| `table` | `q43_own_table` | `table` | yes_no_enum |
| `electric_iron` | `q44_own_electriciron` | `electric_iron` | yes_no_enum |
| `bank_account` | `q45_own_bankaccount` | `bank_account` | yes_no_enum |
| `air_condition` | `q46_own_aircondition` | `ac` | yes_no_enum |
| `generator` | `q47_own_generator` | `generator` | yes_no_enum |
| `water_source` | `q48_Maindrinkwater_source` | `drinking_water_source` | character varying |
| `other_water_source` | `q48a_Otherwater_source` | `drinking_water_source_others` | character varying |
| `water_source2` | `q49_wateruse_source` | `cooking_water_source` | character varying |
| `other_water_source2` | `q49a_Otherwateruse_source` | `cooking_water_source_others` | character varying |
| `water_location` | `q50_Water_location` | `cooking_water_source_location` | character varying |
| `source_water_min` | `q51_Timeto_watersource` | `minutes_get_water` | smallint |
| `m_source` | `q52_Publictap_mainsource` | `main_water_source` | character varying(8) |
| `constant_flow` | `q53_Water_avail` | `main_water_source_unavailble` | character varying(8) |
| `safe_consumption` | `q54_Water_treated` | `main_water_purify` | character varying(10) |
| `water_treatment` | `q55_dotowater_safe` | `water_treatment` | character varying(60) |
| `water_treatment/boil` | `q55a_Boil` | `boil` | yes_no_enum |
| `water_treatment/add_bleach_chlorine` | `q55a_Bleach_Chlor` | `bleach_chlorine` | yes_no_enum |
| `water_treatment/strain_through_a_cloth` | `q55a_Strain_cloth` | `cloth_strain` | yes_no_enum |
| `water_treatment/use_water_filter` | `q55a_Water_filter` | `water_filter` | yes_no_enum |
| `water_treatment/solar_disinfection` | `q55a_Solar_disinfection` | `solar_disinfection` | yes_no_enum |
| `water_treatment/let_it_stand_and_settle` | `q55a_Stand_Settle` | `stand_settle` | yes_no_enum |
| `water_treatment/alum` | `q55a_Alum` | `alum` | yes_no_enum |
| `water_treatment/other` | `q55a_Other` | `other` | yes_no_enum |
| `water_treatment/don't_know` | `q55a_Don'tknow` | `dont_know` | yes_no_enum |
| `other_water` | `q55a_dotowate_safe_spec` | `other_water_treatment` | character varying |
| `housing` | `q56_Typeof_housing` | `housing_type` | character varying |
| `floor_material` | `q57_floor_material` | `floor_material` | character varying |
| `other_floor_material` | `q57a_mainfloor_spec` | `floor_material_others` | character varying |
| `roof_material` | `q58_roof_material` | `roof_material` | character varying |
| `other_roof_material` | `q58a_mainroof_spec` | `roof_material_others` | character varying |
| `wall_material` | `q59_wall_material` | `wall_material` | character varying |
| `other_wall_material` | `q59a_mainwall_spec` | `wall_material_others` | character varying |
| `toilet_facility` | `q60_Typeof_toilfaci` | `toilet_facility_type` | character varying |
| `other_toilet_facility` | `q60a_Toiletfacil_spec` | `toilet_facility_type_others` | character varying |
| `shared_toilet` | `q61_Shared_toilet` | `shared_toilet_facility` | character varying(4) |
| `no_use_toilet` | `q62_Numberthat_usetoilet` | `toilet_facility_households_count` | smallint |
| `toilet_location` | `q63_Toilet_location` | `toilet_facility_location` | character varying |
| `energy_source` | `q64_energy_source` | `cooking_fuel` | character varying |
| `other_energy_source` | `q64a_otherenergy_spec` | `cooking_fuel_others` | character varying |
| `cooking_location` | `q65_cooking_location` | `cooking_location` | character varying |
| `other_cooking_location` | `q65a_othercookingplac_spec` | `cooking_location_others` | character varying |
| `separate_location` | `q66_Separateroom_kitchen` | `separate_kitchen` | character varying(4) |
| `live_stock` | `q67_own_livestocks` | `other_livestock_herds` | character varying(4) |
| `livestock_owned` | `q68_howmany_animals` | `livestock_owned` | character varying(80) |
| `livestock_owned/milk_cows_or_bulls` | `q68a_Own_milkcows_bul` | `cows` | yes_no_enum |
| `livestock_owned/horses_donkeys_or_mules` | `q68a_Own_Horsesdonkeys` | `horses` | yes_no_enum |
| `livestock_owned/goats` | `q68a_Own_Goats` | `goats` | yes_no_enum |
| `livestock_owned/sheep` | `q68a_Own_Sheep` | `sheep` | yes_no_enum |
| `livestock_owned/chickens_or_other_poultry` | `q68a_Own_Chickens` | `chickens` | yes_no_enum |
| `livestock_owned/pigs` | `q68a_Own_Pigs` | `pigs` | yes_no_enum |
| `livestock_owned/camels` | `q68a_Own_Camels` | `camels` | yes_no_enum |
| `livestock_owned/other` | `q68a_Own_othercattle` | `other_cattle` | yes_no_enum |
| `other_livestock` | `q68_Otherlivestock_spec` | `other_livestock_not_mentioned` | character varying |
| `land` | `q69_Own_Agricland` | `agricultural_land` | character varying(4) |
| `land_type` | `q70_typeof_Agricland` | `land_type` | character varying(30) |
| `land_type/plot` | `q70_Own_plot` | `plot` | yes_no_enum |
| `land_type/acres` | `q70_Own_Acres` | `acres` | yes_no_enum |
| `land_type/hectares` | `q70_Own_Hectar` | `hectares` | yes_no_enum |
| `land_quantity` | `q70a_Numof_plots` | `plots_count` | smallint |
| `land_quantity1` | `q70a_Numof_acres` | `acres_count` | smallint |
| `land_quantity2` | `q70a_Numof_hectars` | `hectares_count` | smallint |
| `washing_hand` | `q71_Placefor_handwashing` | `household_handwash_use` | character varying |
| `water_avail` | `q72_Presenceof_water` | `observe_water` | character varying |
| `soap_avail` | `q73_Soap_detergcleaning` | `soap_avail` | character varying(30) |
| `soap_avail/soap` | `q73a_Barliq_powpaste` | `soap` | yes_no_enum |
| `soap_avail/ash_mud` | `q73a_Ash_Mud_Sand` | `ash` | yes_no_enum |
| `soap_avail/none_of_these_present` | `q73a_None_present` | `none` | yes_no_enum |
| `shower_place` | `q74_Havebath_shower` | `bath_in_dwelling` | character varying |
| `water_avail_there` | `q75_Water_available` | `water_available` | character varying(4) |
| `bedroom` | `q76_Numof_bedrooms` | `bedrooms_count` | smallint |
| `bedroom_used` | `q77_Roomsuse_forsleeping` | `sleeping_rooms_count` | smallint |
| `no_bedroom` | `q78_Numsleep_inaroom` | `sleeping_people_count` | smallint |
| `number_nets` | `q79_Have_mosquitonet` | `household_nets` | character varying(4) |
| `mosquito_net` | `q80_Howmany_mosquitonet` | `nets_count` | smallint |
| `mda1` | `q86_Visithome_offerdrugs` | `visit` | character varying(4) |
| `mda_other_visit` | `q86b_ifnothomewhere_drugsoffer` | `ifnothomewhere_drugsoffer` | character varying(30) |
| `mda_reason` | `q87_Reasons_offerdrug` | `mda_reason` | character varying |
| `mda_reason/it_prevents_child_death` | `q87a_prevent_childdeath` | `prevents_death` | yes_no_enum |
| `mda_reason/it_improves_child_health` | `q87a_improves_childhealth` | `improves_health` | yes_no_enum |
| `mda_reason/it_is_part_of_a_research_study` | `q87a_Partof_research` | `research` | yes_no_enum |
| `mda_reason/the_health_worker_did_not_explain_why_they_were_offering_this_drug` | `q87a_Noexplanation_offered` | `no_explanation` | yes_no_enum |
| `mda_reason/don’t_know` | `q87a_Dont_remember` | `dont_remember` | yes_no_enum |
| `mda_reason/other` | `q87a_Other_reasons` | `other_reason` | yes_no_enum |
| `mda_reasons` | `q87a_Otherreason_spec` | `mention_other_reason` | character varying |
| `time_spent` | `q102_TimespendbyCDD_HH` | `cdd_minutes` | smallint |
| `azt_knowledge` | `q103_KnowAZM_distribution` | `distribution_awareness` | character varying(7) |
| `how_aztknowledge` | `q104_Howdid_KnowAZMdist` | `azt_knowledge` | character varying(280) |
| `how_aztknowledge/sarmaan_poster_in_the_village` | `q104_KnowAZM_Sarmaanposter` | `mda_awareness_poster` | yes_no_enum |
| `how_aztknowledge/town_criers` | `q104a_KnowAZM_Towncriers` | `mda_awareness_town_criers` | yes_no_enum |
| `how_aztknowledge/radio_jingles` | `q104a_KnowAZM_Radiojingles` | `mda_awareness_radio_jingles` | yes_no_enum |
| `how_aztknowledge/don't_know_cannot_recall` | `q104a_KnowAZM_Cannotrecall` | `mda_awareness_dont_know` | yes_no_enum |
| `how_aztknowledge/family_member_friend_neighbor` | `q104a_KnowAZM_Famlyfrienneigbor` | `mda_awareness_family_member` | yes_no_enum |
| `how_aztknowledge/professional_health_staff` | `q104a_KnowAZM_Proffhealthstaff` | `mda_awareness_professional` | yes_no_enum |
| `how_aztknowledge/community_drug_distributor_community_health_worker_teacher` | `q104a_KnowAZM_CDD` | `mda_awareness_cdd` | yes_no_enum |
| `how_aztknowledge/community_or_religious_leader` | `q104a_KnowAZM_Communrelleaders` | `mda_awareness_leader` | yes_no_enum |
| `how_aztknowledge/brochuresflyers` | `q104a_KnowAZM_Flyers` | `mda_awareness_flyers` | yes_no_enum |
| `how_aztknowledge/banners` | `q104a_KnowAZM_Banners` | `mda_awareness_banners` | yes_no_enum |
| `how_aztknowledge/radio` | `q104a_KnowAZM_Radio` | `mda_awareness_radio` | yes_no_enum |
| `how_aztknowledge/tv` | `q104a_KnowAZM_Tv` | `mda_awareness_tv` | yes_no_enum |
| `how_aztknowledge/social_media` | `q104a_KnowAZM_Socialmedia` | `mda_awareness_social_media` | yes_no_enum |
| `how_aztknowledge/refused_to_answer` | `q104a_KnowAZM_Refusetoanswer` | `mda_awareness_refused to_answer` | character varying(4) |
| `how_aztknowledge/other` | `q104a_KnowAZM_other` | `mda_awareness_other` | yes_no_enum |
| `other_howazt` | `q104a_KnowAZM_spec` | `mda_awareness_other_mentioned` | character varying |
| `c_offer` | `q105_Atleastone_childoffer` | `offered_at_least_a_child` | character varying(4) |
| `participation_reason` | `q106_Whyallow_childoffer` | `participation_reason` | character varying(70) |
| `participation_reason/c_leader` | `q106_Whyallow_communityleader` | `informed_by_leader` | yes_no_enum |
| `participation_reason/imam` | `q106a_Whyallow_informedbyimam` | `informed_by_imam` | yes_no_enum |
| `participation_reason/h_worker` | `q106a_Whyallow_informedbyHW` | `informed_by_hw` | yes_no_enum |
| `participation_reason/c_sick` | `q106a_Whyallow_childfallsick` | `worried_about_sickness` | yes_no_enum |
| `participation_reason/p_study` | `q106a_Whyallow_takepartinreseach` | `research_participation` | yes_no_enum |
| `participation_reason/c_healthy` | `q106a_Whyallow_childtobehealthy` | `healthy_child` | yes_no_enum |
| `participation_reason/no_reason` | `q106a_Whyallow_nospecreason` | `no_specific_reason` | yes_no_enum |
| `participation_reason/e_taking_it` | `q106a_Whyallow_everyoneistaking` | `everyone_taking_it` | yes_no_enum |
| `participation_reason/r_answer` | `q106a_Whyallow_refusedtoanswer` | `refused_to_answer` | yes_no_enum |
| `participation_reason/other` | `q106a_Whyallow_others` | `program_others` | yes_no_enum |
| `other_participation` | `q106a_Whyallow_otherspec` | `program_others_mentioned` | character varying |
| `c_necessary` | `q107_ThinkAZM_necessary` | `azith_necessary` | character varying(10) |
| `why_necessary` | `q108_WhythinkAZM_necessary` | `why_necessary` | character varying |
| `why_necessary/prevention_of_trachoma` | `q108_ThinkAZM_preventTrachoma` | `prevention_trachoma` | yes_no_enum |
| `why_necessary/prevention_of_guineaworm` | `q108a_ThinkAZM_preventGuineaworm` | `prevention_guinea_worm` | yes_no_enum |
| `why_necessary/prevention_of_onchocerciasis` | `q108a_ThinkAZM_preventOncho` | `prevention_onchocerciasis` | yes_no_enum |
| `why_necessary/prevention_of_polio` | `q108a_ThinkAZM_preventPolio` | `prevention_polio` | yes_no_enum |
| `why_necessary/prevention_of_malaria` | `q108a_ThinkAZM_preventMalaria` | `prevention_malaria` | yes_no_enum |
| `why_necessary/prevention_of_diarrhoea` | `q108a_ThinkAZM_preventDiarrhoea` | `prevention_diarrhoea` | yes_no_enum |
| `why_necessary/prevention_of_respiratory_tract_infection` | `q108a_ThinkAZM_preventRTI` | `prevention_rti` | yes_no_enum |
| `why_necessary/prevention_of_febrile_illness` | `q108a_ThinkAZM_preventFebrilnes` | `prevention_febrile` | yes_no_enum |
| `why_necessary/prevention_of_diseases_that_can_be_avoided_by_vaccines` | `q108a_ThinkAZM_preventvacdisease` | `prevention_avoid_vaccines` | yes_no_enum |
| `why_necessary/prevention_of_death` | `q108a_ThinkAZM_preventdeath` | `prevention_death` | yes_no_enum |
| `why_necessary/don’t_know` | `q108a_ThinkAZM_preventdontknow` | `prevention_dont_know` | yes_no_enum |
| `why_necessary/other` | `q108a_ThinkAZM_preventothers` | `prevention_other` | yes_no_enum |
| `other_why` | `q108a_ThinkAZM_preventspec` | `prevention_other_mentioned` | character varying |
| `thoughts_treatment` | `q109_Like_Communitytreatment` | `thoughts_treatment` | character varying(280) |
| `thoughts_treatment/house_to_house_treatment_makes_it_easy` | `q109_Like_housetohouse` | `liked_house_2_house` | yes_no_enum |
| `thoughts_treatment/trusted_distributors_cdds_from_the_community` | `q109a_Like_trusteddist` | `liked_trusted_cdds` | yes_no_enum |
| `thoughts_treatment/no_long_wait_for_drugs` | `q109a_Like_nolongwait` | `liked_no_long_wait` | yes_no_enum |
| `thoughts_treatment/free_drugs` | `q109a_Like_freedrugs` | `liked_free_drugs` | yes_no_enum |
| `thoughts_treatment/no_specific_part_i_liked` | `q109a_Like_nospecpart` | `liked_no_specific` | yes_no_enum |
| `thoughts_treatment/refused_to_answer` | `q109a_Like_refusedtoanswer` | `liked_refused_to_answer` | yes_no_enum |
| `thoughts_treatment/other` | `q109a_Like_other` | `liked_other` | yes_no_enum |
| `other_thoughts` | `q109a_Like_spec` | `liked_other_mentioned` | character varying |
| `thoughts_treatment2` | `q110_Dislike_treatmentprog` | `dislike_treatment_thoughts` | character varying |
| `thoughts_treatment2/inconvenient_time` | `q110_Dislike_timeinconvinient` | `dislike_inconvenient_time` | yes_no_enum |
| `thoughts_treatment2/unfriendly_distributors_cdds` | `q110a_Dislike_unfriendlyCDDs` | `dislike_unfriendly_cdds` | yes_no_enum |
| `thoughts_treatment2/drugs_were_not_available_or_got_finished` | `q110a_Dislike_drugsnotavail` | `dislike_drugs_finished` | yes_no_enum |
| `thoughts_treatment2/long_duration_of_time` | `q110a_Dislike_longtimeduration` | `dislike_long_time` | yes_no_enum |
| `thoughts_treatment2/adverse_drug_reaction` | `q110a_Dislike_adversereaction` | `dislike_adverse_drug_reaction` | yes_no_enum |
| `thoughts_treatment2/did_not_give_treatment_for_other_diseases` | `q110a_Dislike_notothertreatment` | `dislike_diseases` | yes_no_enum |
| `thoughts_treatment2/refused_to_answer` | `q110a_Dislike_refusedtoanswer` | `dislike_refused_to_answer` | yes_no_enum |
| `thoughts_treatment2/other` | `q110a_Dislike_others` | `dislike_other` | yes_no_enum |
| `other_thoughts2` | `q110a_Dislike_spec` | `dislike_other_mentioned` | character varying |
| `challenge_azt` | `q111_Challenges_obstacle` | `challenge_azt` | character varying |
| `challenge_azt/financial_constraints` | `q111_Challenges_Finconstrain` | `challenges_finance_constraints` | yes_no_enum |
| `challenge_azt/lack_of_transportation` | `q111a_Challenges_lacktransport` | `challenges_lack_transportation` | yes_no_enum |
| `challenge_azt/lack_of_awareness` | `q111a_Challenges_lackawarenes` | `challenges_lack_awareness` | yes_no_enum |
| `challenge_azt/cultural_beliefs` | `q111a_Challenges_cultrualbeliefs` | `challenges_cultural_beliefs` | yes_no_enum |
| `challenge_azt/others` | `q111a_Challenges_others` | `challenges_others` | yes_no_enum |
| `challenge_azt/none` | `q111a_Challenges_none` | `challenges_none` | yes_no_enum |
| `other_challenge` | `q111a_Challenges_spec` | `challenges_other_mentioned` | character varying |
| `drugs_again` | `q112_Happyforchild_takedrug` | `drugs_in_future` | character varying(8) |
| `drugss_again` | `q113_whynotwant_takedrug` | `no_drugs_in_future` | character varying |
| `drugss_again/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | `q113_whynotwant_sideeffects` | `drugs_in_future_side_effects` | yes_no_enum |
| `drugss_again/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | `q113a_whynotwant_childnotatrisk` | `drugs_in_future_child_not_at_risk` | yes_no_enum |
| `drugss_again/medicine_doesn’t_work` | `q113a_whynotwant_medicinenotwork` | `drugs_in_future_ineffective_medicine` | yes_no_enum |
| `drugss_again/negative_experience_with_distributors_cdds` | `q113a_whynotwant_negexpwithCDDs` | `drugs_in_future_negative_cdds` | yes_no_enum |
| `drugss_again/refused_to_answer` | `q113a_whynotwant_refusedtoanswer` | `drugs_in_future_dislike_refused_to_answer` | yes_no_enum |
| `drugss_again/other` | `q113a_whynotwant_other` | `drugs_in_future_other` | yes_no_enum |
| `drugggs_again` | `q114_neighhbor_takedrug` | `neighbors_took_drug` | character varying(10) |
| `next_time` | `q115_Howwant_drugdistributed` | `drugs_in_future_want_it_distributed` | character varying |
| `other_time` | `q115a_Howlikedist_spec` | `drugs_in_future_other_mentioned` | character varying |
| `change` | `q116_Makechange_toparticipate` | `change_routine` | character varying(8) |
| `info1` | `q117_Haveinfo_makeAZMdecision` | `given_information` | agree_disagree |
| `info2` | `q118_littletime_participate` | `short_time` | agree_disagree |
| `info3` | `q119_Comfortable_childtreatment` | `comfortable_location` | agree_disagree |
| `info4` | `q120_Comfortable_healthworker` | `comfortable_hw` | agree_disagree |
| `info5` | `q121_Comfortable_AZMothermedicat` | `comfortable_azith` | agree_disagree |
| `info6` | `q122_Easytopart_AZMprog` | `easy_participation` | agree_disagree |
| `info7` | `q123_Givechild_AZMfutureHW` | `give_azith_in_future` | agree_disagree |
| `info8` | `q124_ThinkAZM_usefulinterv` | `useful_intervention` | yes_no_enum |
| `info9` | `q125_Importantof_AZMtochild` | `azith_rating` | smallint |
| `willingness` | `q126_Howmuch_payforadose` | `azith_dose_pay` | integer |
| `min_amount` | `q127_Howmuch_minimum` | `min_pay` | integer |
| `max_amount` | `q128_Howmuch_maximum` | `max_pay` | integer |
| `willingness1` | `q129_whywilling_topay` | `willingness_to_pay` | character varying |
| `willingness1/it_will_help_my_child_from_falling_ill` | `q129a_Whypay_helpchildillness` | `willing_prevent_illness` | yes_no_enum |
| `willingness1/it_will_help_prevent_my_child_from_dying` | `q129a_Whypay_helpchilddying` | `willing_prevent_death` | yes_no_enum |
| `willingness1/it_will_aid_the_growth_of_my_child` | `q129a_Whypay_aidchildgrowth` | `willing_aid_growth` | yes_no_enum |
| `willingness1/it_would_be_cheaper_i_have_the_money` | `q129a_Whypay_havemoney` | `willing_have_money` | yes_no_enum |
| `willingness1/other` | `q129a_Whypay_other` | `willing_other_reason` | yes_no_enum |
| `willingness1/don’t_know` | `q129a_Whypay_dontknow` | `willing_dont_know` | yes_no_enum |
| `other_willingness1` | `q129a_Whypay_spec` | `willing_other_reason_mentioned` | character varying |
| `willingness3` | `q130_whynotwilling_topay` | `not_willingto_pay` | character varying |
| `willingness3/it_has_no_benefit_to_my_child's_health` | `q130_Whynotpay_nobenefit` | `not_willing_no_benefit` | yes_no_enum |
| `willingness3/don’t_have_the_money` | `q130a_Whynotpay_donthavemoney` | `not_willing_no_money` | yes_no_enum |
| `willingness3/government_should_continue_to_make_it_free` | `q130a_Whynotpay_makeitfree` | `not_willing_govt_free` | yes_no_enum |
| `willingness3/don’t_know` | `q130a_Whynotpay_dontknow` | `not_willing_dont_know` | yes_no_enum |
| `willingness3/other` | `q130a_Whynotpay_other` | `not_willing_other_reason` | yes_no_enum |
| `other_willingness3` | `q130a_Whynotpay_spec` | `not_willing_other_reason_mentioned` | character varying |
| `info_x` | `q131_Value_symptRTI` | `rti_treatment_value` | treat_value |
| `info_y` | `q132_Value_symptADD` | `diarrhoea_treatment_value` | treat_value |
| `info_q` | `q133_Value_symptAFI` | `febrile_illness_treatment_value` | treat_value |
| `info11` | `q134_Spend_Healthcareexp` | `current_healthcare_expenses` | integer |
| `info12` | `q135_willinspend_RTIepisode` | `rti_prevention_cost` | integer |
| `info13` | `q136_willingspend_Diarreah` | `diarrhea_prevention_cost` | integer |
| `info14` | `q137_willingspend_Malaria` | `malaria_prevention_cost` | integer |
| `_uuid` | `uuid` | `household_uuid` | uuid |
| computed (see Keys) | `concatenated_id` | `concatenated_id` | character varying |
| `_index` | `index` | `index` | int |

</details>

---

## All children

**Kobo sheet:** `child_info` repeat

### Kobo → `raw_data.coverage_all_children` (20 columns, all TEXT)

<details><summary>Show columns</summary>

| Kobo column | Kobo type | Raw DB column |
|---|---|---|
| `child_id` | calculate | `child_id` |
| `child_name` | text | `child_name` |
| `age_eligible` | integer | `age_eligible` |
| `is_eligible` | calculate | `is_eligible` |
| `child_label` | calculate | `child_label` |
| `_index` | Kobo system | `_index` |
| `_parent_table_name` | Kobo system | `_parent_table_name` |
| `_parent_index` | Kobo system | `_parent_index` |
| `_submission__id` | Kobo system | `_submission__id` |
| `_submission__uuid` | Kobo system | `_submission__uuid` |
| `_submission__submission_time` | Kobo system | `_submission__submission_time` |
| `_submission__validation_status` | Kobo system | `_submission__validation_status` |
| `_submission__notes` | Kobo system | `_submission__notes` |
| `_submission__status` | Kobo system | `_submission__status` |
| `_submission__submitted_by` | Kobo system | `_submission__submitted_by` |
| `_submission___version__` | Kobo system | `_submission___version__` |
| `_submission__tags` | Kobo system | `_submission__tags` |
| `_submission_meta/rootUuid` | Kobo system | `_submission_meta_rootuuid` |
| `child_id_submission__uuid` | computed | `child_id_submission__uuid` |
| `_parent_index_submission__uuid` | computed | `_parent_index_submission__uuid` |

</details>

### Kobo → `sarmaan2data.coverage_all_children` (15 columns)

<details><summary>Show columns</summary>

| Kobo column | After step 2 | Clean DB column | Postgres type |
|---|---|---|---|
| joined from household | `q1_States` | `state` | character varying(20) |
| joined from household | `q2_LGAs` | `lga` | character varying(40) |
| joined from household | `q3_Wards` | `ward` | character varying(50) |
| joined from household | `q4_Community` | `community` | character varying(100) |
| joined from household | `q6_HH_number` | `household_no` | smallint |
| joined from household | `unique_code` | `household_code` | character varying(11) |
| `child_id` | `child_id` | `child_id` | smallint |
| `child_name` | `child_name` | `child_name` | character varying(30) |
| `age_eligible` | `q88_Age_child` | `age_eligible` | smallint |
| `is_eligible` | `eligibility` | `is_eligible` | character varying(2) |
| `_index` | `_index` | `_index` | smallint |
| `_parent_index` | `index` | `parent_index` | smallint |
| `_submission__uuid` | `_submission__uuid` | `childd_uuid` | uuid |
| computed (see Keys) | `concatenated_id` | `concatenated_id` | character varying |
| computed: `child_id` + `_submission__uuid` | `child_id_childd_uuid` | `child_id_childd_uuid` | character varying |

</details>

---

## Nets

**Kobo sheet:** `net_repeat` repeat

### Kobo → `raw_data.coverage_net_info` (39 columns, all TEXT)

<details><summary>Show columns</summary>

| Kobo column | Kobo type | Raw DB column |
|---|---|---|
| `net_id` | calculate | `net_id` |
| `net_received` | select_one | `net_received` |
| `how_received` | select_one | `how_received` |
| `where_net` | select_one | `where_net` |
| `other_where_net` | text | `other_where_net` |
| `under_mosquito_net` | select_one | `under_mosquito_net` |
| `no_sleep_net` | select_multiple | `no_sleep_net` |
| `no_sleep_net/no_mosquitoes` | select_multiple | `no_sleep_net_no_mosquitoes` |
| `no_sleep_net/no_malaria` | select_multiple | `no_sleep_net_no_malaria` |
| `no_sleep_net/too_hot` | select_multiple | `no_sleep_net_too_hot` |
| `no_sleep_net/difficult_to_hang` | select_multiple | `no_sleep_net_difficult_to_hang` |
| `no_sleep_net/don't_like_smell` | select_multiple | `no_sleep_net_dont_like_smell` |
| `no_sleep_net/feel_closed_in_or_constrained` | select_multiple | `no_sleep_net_feel_closed_in_or_constrained` |
| `no_sleep_net/net_too_old_torn` | select_multiple | `no_sleep_net_net_too_old_torn` |
| `no_sleep_net/net_too_dirty` | select_multiple | `no_sleep_net_net_too_dirty` |
| `no_sleep_net/net_not_available_last_night_washing` | select_multiple | `no_sleep_net_net_not_available_last_night_washing` |
| `no_sleep_net/feel_itn_chemicals_are_unsafe` | select_multiple | `no_sleep_net_feel_itn_chemicals_are_unsafe` |
| `no_sleep_net/it_provokes_cough` | select_multiple | `no_sleep_net_it_provokes_cough` |
| `no_sleep_net/users_did_not_sleep_here_last_night` | select_multiple | `no_sleep_net_users_did_not_sleep_here_last_night` |
| `no_sleep_net/net_not_needed_last_night` | select_multiple | `no_sleep_net_net_not_needed_last_night` |
| `no_sleep_net/no_space_to_hang` | select_multiple | `no_sleep_net_no_space_to_hang` |
| `no_sleep_net/other` | select_multiple | `no_sleep_net_other` |
| `no_sleep_net/don’t_know` | select_multiple | `no_sleep_net_dont_know` |
| `other_net` | text | `other_net` |
| `_index` | Kobo system | `_index` |
| `_parent_table_name` | Kobo system | `_parent_table_name` |
| `_parent_index` | Kobo system | `_parent_index` |
| `_submission__id` | Kobo system | `_submission__id` |
| `_submission__uuid` | Kobo system | `_submission__uuid` |
| `_submission__submission_time` | Kobo system | `_submission__submission_time` |
| `_submission__validation_status` | Kobo system | `_submission__validation_status` |
| `_submission__notes` | Kobo system | `_submission__notes` |
| `_submission__status` | Kobo system | `_submission__status` |
| `_submission__submitted_by` | Kobo system | `_submission__submitted_by` |
| `_submission___version__` | Kobo system | `_submission___version__` |
| `_submission__tags` | Kobo system | `_submission__tags` |
| `_submission_meta/rootUuid` | Kobo system | `_submission_meta_rootuuid` |
| `net_id_submission__uuid` | computed | `net_id_submission__uuid` |
| `_parent_index_submission__uuid` | computed | `_parent_index_submission__uuid` |

</details>

### Kobo → `sarmaan2data.coverage_net_info` (35 columns)

<details><summary>Show columns</summary>

| Kobo column | After step 2 | Clean DB column | Postgres type |
|---|---|---|---|
| joined from household | `q1_States` | `state` | character varying(20) |
| joined from household | `q2_LGAs` | `lga` | character varying(40) |
| joined from household | `q3_Wards` | `ward` | character varying(50) |
| joined from household | `q4_Community` | `community` | character varying(100) |
| joined from household | `q6_HH_number` | `household_no` | smallint |
| joined from household | `unique_code` | `household_code` | character varying(11) |
| `net_id` | `net_ID` | `net_id` | smallint |
| `net_received` | `q81_whengot_net` | `got_net_when` | character varying(25) |
| `how_received` | `q82_Howgot_net` | `net_source` | character varying(25) |
| `where_net` | `q83_wheregot_net` | `net_received_location` | character varying(25) |
| `other_where_net` | `q83_wheregotnet_spec` | `other_net_received_location` | character varying(40) |
| `under_mosquito_net` | `q84_sleepunder_net` | `net_sleep` | character varying(20) |
| `no_sleep_net` | `q85_whynotsleep_net` | `no_sleep_net` | character varying |
| `no_sleep_net/no_mosquitoes` | `q85a_whynotsleep_nomosquito` | `unused_net_no_mosquitoes` | yes_no_enum |
| `no_sleep_net/no_malaria` | `q85a_whynotsleep_nomalaria` | `unused_net_no_malaria` | yes_no_enum |
| `no_sleep_net/too_hot` | `q85a_whynotsleep_toohot` | `unused_net_too_hot` | yes_no_enum |
| `no_sleep_net/difficult_to_hang` | `q85a_whynotsleep_difftohang` | `unused_net_dificult_to_hang` | yes_no_enum |
| `no_sleep_net/don't_like_smell` | `q85a_whynotsleep_dislikesmell` | `unused_net_dislike_smell` | yes_no_enum |
| `no_sleep_net/feel_closed_in_or_constrained` | `q85a_whynotsleep_feelconstrain` | `unused_net_feel_constrained` | yes_no_enum |
| `no_sleep_net/net_too_old_torn` | `q85a_whynotsleep_tooold_torn` | `unused_net_net_old` | yes_no_enum |
| `no_sleep_net/net_too_dirty` | `q85a_whynotsleep_toodirty` | `unused_net_net_dirty` | yes_no_enum |
| `no_sleep_net/net_not_available_last_night_washing` | `q85a_whynotsleep_notavail` | `unused_net_net_unavailable` | yes_no_enum |
| `no_sleep_net/feel_itn_chemicals_are_unsafe` | `q85a_whynotsleep_unsafe` | `unused_net_chemicals_unsafe` | yes_no_enum |
| `no_sleep_net/it_provokes_cough` | `q85a_whynotsleep_provcough` | `unused_net_provokes_cough` | yes_no_enum |
| `no_sleep_net/users_did_not_sleep_here_last_night` | `q85a_whynotsleep_notsleeplasnight` | `unused_net_nobody_slept` | yes_no_enum |
| `no_sleep_net/net_not_needed_last_night` | `q85a_whynotsleep_notneeded` | `unused_net_net_not_needed` | yes_no_enum |
| `no_sleep_net/no_space_to_hang` | `q85a_whynotsleep_nospace` | `unused_net_no_space_to_hang` | yes_no_enum |
| `no_sleep_net/other` | `q85a_whynotsleep_other` | `unused_net_other` | yes_no_enum |
| `no_sleep_net/don’t_know` | `q85a_whynotsleep_dontknow` | `unused_net_dont_know` | yes_no_enum |
| `other_net` | `q85a_whynotsleep_spec` | `unused_net_other_mentioned` | character varying |
| `_index` | `index` | `index` | integer |
| `_submission__uuid` | `uuid` | `net_uuid` | uuid |
| `_index` | `index` | `parent_index` | integer |
| computed (see Keys) | `concatenated_id` | `concatenated_id` | character varying |
| computed: `net_ID` + `uuid` | `net_id_net_uuid` | `net_id_net_uuid` | character varying |

</details>

---

## Children 1–59 months

**Kobo sheet:** `child_infoo` repeat

### Kobo → `raw_data.coverage_children_1_59` (88 columns, all TEXT)

<details><summary>Show columns</summary>

| Kobo column | Kobo type | Raw DB column |
|---|---|---|
| `child_idd` | calculate | `child_idd` |
| `unique_code2` | calculate | `unique_code2` |
| `child_iden` | text | `child_iden` |
| `child_names11` | select_one | `child_name` |
| `sex_eligible` | select_one | `sex_eligible` |
| `drug_offer` | select_one | `drug_offer` |
| `not_offered` | select_multiple | `not_offered` |
| `not_offered/parent_care_giver_unaware_of_mda` | select_multiple | `not_offered_parent` |
| `not_offered/distributor_did_not_come_to_my_house_school_fixed_point_location` | select_multiple | `not_offered_distributor` |
| `not_offered/child_was_taking_other_medications` | select_multiple | `not_offered_medications` |
| `not_offered/child_was_not_available` | select_multiple | `not_offered_unavailable` |
| `not_offered/drugs_were_not_available_or_got_finished` | select_multiple | `not_offered_drugs_not_avail` |
| `not_offered/parent_caregiver_was_too_far_away_or_was_busy` | select_multiple | `not_offered_parent_far` |
| `not_offered/refused_to_answer` | select_multiple | `not_offered_refused` |
| `not_offered/other` | select_multiple | `not_offered_other` |
| `other_not_offered` | text | `other_not_offered` |
| `refusal` | select_multiple | `refusal` |
| `refusal/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | select_multiple | `refusal_afraid` |
| `refusal/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | select_multiple | `refusal_parent` |
| `refusal/medicine_doesn’t_work` | select_multiple | `refusal_medicine` |
| `refusal/negative_experience_with_distributors_cdds` | select_multiple | `refusal_negative` |
| `refusal/refused_to_answer` | select_multiple | `refusal_refused` |
| `refusal/other` | select_multiple | `refusal_other` |
| `other_refusal` | text | `other_refusal` |
| `weight_eligible` | select_one | `weight_eligible` |
| `swallow` | select_one | `swallow` |
| `p_swallow` | select_one | `p_swallow` |
| `no_swallow` | select_multiple | `no_swallow` |
| `no_swallow/parent_caregiver_didnot_want_child_to_take_medicine` | select_multiple | `no_swallow_parent` |
| `no_swallow/child_was_sick` | select_multiple | `no_swallow_sick` |
| `no_swallow/child_was_taking_other_medications` | select_multiple | `no_swallow_medications` |
| `no_swallow/child_refused_to_take_drug` | select_multiple | `no_swallow_refused` |
| `no_swallow/child_not_available` | select_multiple | `no_swallow_unavailable` |
| `no_swallow/refused_to_answer` | select_multiple | `no_swallow_refused_answer` |
| `no_swallow/other` | select_multiple | `no_swallow_other` |
| `other_swallow` | text | `other_swallow` |
| `p_refusal` | select_multiple | `p_refusal` |
| `p_refusal/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | select_multiple | `p_refusal_afraid` |
| `p_refusal/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | select_multiple | `p_refusal_parent` |
| `p_refusal/medicine_doesn’t_work` | select_multiple | `p_refusal_medicine` |
| `p_refusal/negative_experience_with_distributors_cdds` | select_multiple | `p_refusal_negative` |
| `p_refusal/refused_to_answer` | select_multiple | `p_refusal_refused` |
| `p_refusal/other` | select_multiple | `p_refusal_other` |
| `other_refusal_swallow` | text | `other_refusal_swallow` |
| `ns_reaction` | select_one | `ns_reaction` |
| `child_reaction1` | select_multiple | `child_reaction` |
| `child_reaction1/vomiting` | select_multiple | `child_reaction_vomiting` |
| `child_reaction1/passage_of_watery_stools` | select_multiple | `child_reaction_stools` |
| `child_reaction1/excessive_crying` | select_multiple | `child_reaction_crying` |
| `child_reaction1/skin_rashes` | select_multiple | `child_reaction_skin` |
| `child_reaction1/body_itching` | select_multiple | `child_reaction_itching` |
| `child_reaction1/abdominal_pain` | select_multiple | `child_reaction_abd_pain` |
| `child_reaction1/refused` | select_multiple | `child_reaction_refused` |
| `child_reaction1/other` | select_multiple | `child_reaction_other` |
| `other_child_reaction` | text | `other_child_reaction` |
| `stat_reaction` | select_one | `stat_reaction` |
| `management` | select_multiple | `management` |
| `management/informed_the_healthcare_worker_who_reassured_me` | select_multiple | `management_informed_worker` |
| `management/my_child_was_admitted` | select_multiple | `management_admitted` |
| `management/went_to_a_nearby_health_facility_and_received_an_injection_only` | select_multiple | `management_nearby_injection` |
| `management/received_both_an_injection_and_oral_drugs` | select_multiple | `management_both_drugs` |
| `management/received_oral_drugs_only` | select_multiple | `management_oral_only` |
| `management/did_not_inform_anyone` | select_multiple | `management_did_not_inform` |
| `management/was_not_concerned_disturbed` | select_multiple | `management_not_concerned` |
| `management/went_to_the_health_facility_where_the_azm_was_administered` | select_multiple | `management_health_facility` |
| `management/refused_to_answer` | select_multiple | `management_refused` |
| `management/others` | select_multiple | `management_other` |
| `other_mange` | text | `other_manage` |
| `card_avail` | select_one | `card_avail` |
| `card_image` | image | `card_image` |
| `card_image_URL` | derived by Kobo export / preprocessor | `card_image_url` |
| `card_not_avail` | text | `card_not_avail` |
| `_index` | Kobo system | `_index` |
| `_parent_table_name` | Kobo system | `_parent_table_name` |
| `_parent_index` | Kobo system | `_parent_index` |
| `_submission__id` | Kobo system | `_submission__id` |
| `_submission__uuid` | Kobo system | `_submission__uuid` |
| `_submission__submission_time` | Kobo system | `_submission__submission_time` |
| `_submission__validation_status` | Kobo system | `_submission__validation_status` |
| `_submission__notes` | Kobo system | `_submission__notes` |
| `_submission__status` | Kobo system | `_submission__status` |
| `_submission__submitted_by` | Kobo system | `_submission__submitted_by` |
| `_submission___version__` | Kobo system | `_submission___version__` |
| `_submission__tags` | Kobo system | `_submission__tags` |
| `_submission_meta/rootUuid` | Kobo system | `_submission_meta_rootuuid` |
| `child_idd_submission__uuid` | computed | `child_idd_submission__uuid` |
| `agee_eligible` | derived by Kobo export / preprocessor | `age_eligible` |
| `_parent_index_submission__uuid` | computed | `_parent_index_submission__uuid` |

</details>

### Kobo → `sarmaan2data.coverage_children_1_59` (83 columns)

<details><summary>Show columns</summary>

| Kobo column | After step 2 | Clean DB column | Postgres type |
|---|---|---|---|
| joined from household | `q1_States` | `state` | character varying(20) |
| joined from household | `q2_LGAs` | `lga` | character varying(40) |
| joined from household | `q3_Wards` | `ward` | character varying(50) |
| joined from household | `q4_Community` | `community` | character varying(100) |
| joined from household | `q6_HH_number` | `household_no` | smallint |
| joined from household | `unique_code` | `household_code` | character varying(11) |
| `child_idd` | `child_idd` | `child_id` | smallint |
| `unique_code2` | `unique_code2` | `child_code` | character varying(13) |
| `child_names11` | `child_names` | `child_name` | character varying(30) |
| `agee_eligible` | `q88_Ageof_child` | `child_age` | smallint |
| `sex_eligible` | `q89_Sexof_child` | `child_gender` | child_gender_enum |
| `drug_offer` | `q90_Offered_drugs` | `child_drug` | child_drug_enum |
| `not_offered` | `q91_Whychild_Notoffered` | `not_offered` | character varying |
| `not_offered/parent_care_giver_unaware_of_mda` | `q91_Notoffered_unawareofMDA` | `not_offered_parent_unaware` | yes_no_enum |
| `not_offered/distributor_did_not_come_to_my_house_school_fixed_point_location` | `q91a_Notoffered_distributnotcom` | `not_offered_fixed_point` | yes_no_enum |
| `not_offered/child_was_taking_other_medications` | `q91a_Notoffered_othermedication` | `not_offered_child_on_other_medications` | yes_no_enum |
| `not_offered/child_was_not_available` | `q91a_Notoffered_childnotavail` | `not_offered_child_unavailable` | yes_no_enum |
| `not_offered/drugs_were_not_available_or_got_finished` | `q91a_Notoffered_drugsnotavail` | `not_offered_drugs_unavailable` | yes_no_enum |
| `not_offered/parent_caregiver_was_too_far_away_or_was_busy` | `q91a_Notoffered_caregivertoofar` | `not_offered_parent_busy` | yes_no_enum |
| `not_offered/refused_to_answer` | `q91a_Notofferd_refusetoanswer` | `not_offered_refused_to_answer` | yes_no_enum |
| `not_offered/other` | `q91a_Notoffered_other` | `not_offered_for_other_reason` | yes_no_enum |
| `other_not_offered` | `q91a_Notoffered_otherspec` | `not_offered_for_other_reason_mentioned` | character varying |
| `refusal` | `q92_Parent_refuseoffer` | `not_offered_parent_refused` | character varying |
| `refusal/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | `q92_Refuseoffer_afraidofsideeff` | `refuse_offer_adverse_reactions` | yes_no_enum |
| `refusal/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | `q92a_Refuseoffer_Childnotatrisk` | `refuse_offer_child_not_at_risk` | yes_no_enum |
| `refusal/medicine_doesn’t_work` | `q92a_Refuseoffer_Meddoesnotwork` | `refuse_offer_medicine_doesnt_work` | yes_no_enum |
| `refusal/negative_experience_with_distributors_cdds` | `q92a_Refuseoffer_NegexperwithCDD` | `refuse_offer_negative_experience_with_cdd` | yes_no_enum |
| `refusal/refused_to_answer` | `q92a_Refuseoffer_refuseanswer` | `refuse_offer_refused_to_answer` | yes_no_enum |
| `refusal/other` | `q92a_Refuseoffer_Others` | `refuse_offer_other` | yes_no_enum |
| `other_refusal` | `q92a_Refuseoffer_otherspec` | `refuse_offer_other_mentioned` | character varying |
| `weight_eligible` | `q93_Weighed_forAZM` | `child_weighed` | character varying(9) |
| `swallow` | `q94_Swallowed_AZMoffered` | `child_swallowed` | character varying(9) |
| `p_swallow` | `q95_Swallowed_DOT` | `child_swallowed_present` | character varying(9) |
| `no_swallow` | `q96_Notswallow_AZM` | `not_swallow` | character varying |
| `no_swallow/parent_caregiver_didnot_want_child_to_take_medicine` | `q96a_Notswallow_parentdidnotwant` | `not_swallow_parent_refused` | yes_no_enum |
| `no_swallow/child_was_sick` | `q96a_Notswallow_childwassick` | `not_swallow_child_sick` | yes_no_enum |
| `no_swallow/child_was_taking_other_medications` | `q96a_Notswallow_Othemedication` | `not_swallow_child_on_other_medications` | yes_no_enum |
| `no_swallow/child_refused_to_take_drug` | `q96a_Notswallow_childrefuse` | `not_swallow_child_refused` | yes_no_enum |
| `no_swallow/child_not_available` | `q96a_Notswallow_childnotavail` | `not_swallow_child_unavailable` | yes_no_enum |
| `no_swallow/refused_to_answer` | `q96a_Notswallow_Refusetoanswer` | `not_swallow_refused_to_answer` | yes_no_enum |
| `no_swallow/other` | `q96a_Notswallow_other` | `not_swallow_for_other_reason` | yes_no_enum |
| `other_swallow` | `q96a_Notswallow_spec` | `not_swallow_for_other_reason_mentioned` | character varying |
| `p_refusal` | `q97_Refuschild_swallow` | `parent_refused_child_swallow` | character varying |
| `p_refusal/afraid_of_side_effects_or_experienced_adverse_drug_reactions_previously` | `q97_Refuswallow_adversereact` | `refuse_swallow_adverse_reactions` | yes_no_enum |
| `p_refusal/parent_caregiver_beleve_the_child_is_not_at_risk_for_this_disease` | `q97a_Refuswallow_notatrisk` | `refuse_swallow_child_not_at_risk` | yes_no_enum |
| `p_refusal/medicine_doesn’t_work` | `q97a_Refuswallow_mednotwork` | `refuse_swallow_medicine_doesnt_work` | yes_no_enum |
| `p_refusal/negative_experience_with_distributors_cdds` | `q97a_Refuswallow_negexpwithCDD` | `refuse_swallow_negative_experience_with_cdd` | yes_no_enum |
| `p_refusal/refused_to_answer` | `q97a_Refuswallow_refusetoanswer` | `refuse_swallow_refused_to_answer` | yes_no_enum |
| `p_refusal/other` | `q97a_Refuswallow_others` | `refuse_swallow_other` | yes_no_enum |
| `other_refusal_swallow` | `q97a_Refuswallow_spec` | `refuse_swallow_other_mentioned` | character varying |
| `ns_reaction` | `q98_childhave_negreaction` | `swallow_negative_reaction` | character varying(8) |
| `child_reaction1` | `q99_Typeof_reaction` | `reaction_type` | character varying (50) |
| `child_reaction1/vomiting` | `q99a_Reaction_vomiting` | `reaction_vomiting` | yes_no_enum |
| `child_reaction1/passage_of_watery_stools` | `q99a_Reaction_waterystool` | `reaction_watery_stools` | yes_no_enum |
| `child_reaction1/excessive_crying` | `q99a_Reaction_excessivecrying` | `reaction_excessive_crying` | yes_no_enum |
| `child_reaction1/skin_rashes` | `q99a_Reaction_skinrashes` | `reaction_skin_rashes` | yes_no_enum |
| `child_reaction1/body_itching` | `q99a_Reaction_bodyitching` | `reaction_body_itching` | yes_no_enum |
| `child_reaction1/abdominal_pain` | `q99a_Reaction_abdominalpain` | `reaction_abdominal_pain` | yes_no_enum |
| `child_reaction1/refused` | `q99a_Reaction_refusetoanswer` | `reaction_refused_answer` | yes_no_enum |
| `child_reaction1/other` | `q99a_Reaction_other` | `reaction_other` | yes_no_enum |
| `other_child_reaction` | `q99a_Reaction_spec` | `reaction_other_mentioned` | character varying |
| `stat_reaction` | `q100_Severityof_reaction` | `severity_of_reaction` | character varying(100) |
| `management` | `q101_Howmanage_reaction` | `negative_reaction_statements` | character varying |
| `management/informed_the_healthcare_worker_who_reassured_me` | `q101a_Managereaction_informHW` | `reaction_managed_informed_health_worker` | yes_no_enum |
| `management/my_child_was_admitted` | `q101a_Managereactn_Childadmitted` | `reaction_managed_child_admitted` | yes_no_enum |
| `management/went_to_a_nearby_health_facility_and_received_an_injection_only` | `q101a_Managereactn_Injectonly` | `reaction_managed_injection` | yes_no_enum |
| `management/received_both_an_injection_and_oral_drugs` | `q101a_Managereactn_injectoraldrug` | `reaction_managed_injection_and_oral_drugs` | yes_no_enum |
| `management/received_oral_drugs_only` | `q101a_Managereactn_oraldrugonly` | `reaction_managed_oral_drugs` | yes_no_enum |
| `management/did_not_inform_anyone` | `q101a_Managereactn_informnoone` | `reaction_managed_informed_no_one` | yes_no_enum |
| `management/was_not_concerned_disturbed` | `q101a_Managereactn_notconcern` | `reaction_managed_not_concerned` | yes_no_enum |
| `management/went_to_the_health_facility_where_the_azm_was_administered` | `q101a_Managereactn_wenttoHF` | `reaction_managed_visited_health_facility` | yes_no_enum |
| `management/refused_to_answer` | `q101a_Manageractn_refusetoanswer` | `reaction_managed_refused` | yes_no_enum |
| `management/others` | `q101a_Manageractn_others` | `reaction_managed_others` | yes_no_enum |
| `other_mange` | `q101a_Managereactn_spec` | `reaction_managed_others_mentioned` | character varying(40) |
| `card_avail` | `AZMCard_retention` | `azm_card` | azm_card_enum |
| `card_image` | `card_image` | `azm_card_image` | character varying(20) |
| `card_image_URL` | `card_image_URL` | `azm_card_url` | character varying |
| `card_not_avail` | `Nocard_reason` | `azm_nocard_reason` | character varying |
| `_index` | `_index` | `index` | smallint |
| `_parent_index` | `_parent_index` | `parent_index` | smallint |
| `_submission__uuid` | `_submission__uuid` | `child_uuid` | uuid |
| computed (see Keys) | `concatenated_id` | `concatenated_id` | character varying |
| computed: `child_idd` + `_submission__uuid` | `child_id_child_uuid` | `child_id_child_uuid` | character varying |

</details>

---

## Location decoding (`mappings/dat.csv`)

`dat.csv` is the sampling frame: `state_Name/Label`, `lga_Name/Label`, `ward_Name/Label`, `settlement_Name/Label`, `sample_count`, `RA Target`. The preprocessor replaces the codes in `states`, `lgas`, `wards`, `community_name` (and `q2_LGAs`, `q3_Wards`, `q4_Community`) with the matching names before any step runs.
