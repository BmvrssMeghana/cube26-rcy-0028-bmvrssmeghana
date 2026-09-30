"""
Eval Dataset — Recovery Manager
Self-constructed evaluation set with deliberately planted known errors.
Ground truth is set by the builder; every row's correct answer is known.

Scenarios covered:
  E-01: inbound_defect_fee — clean prep → CONTRADICTED
  E-02: inbound_defect_fee — bad fnsku placement → SUPPORTED
  E-03: lost_inbound — qty match → CONTRADICTED
  E-04: lost_inbound — short ship → SUPPORTED
  E-05: refund_issued_item_not_returned — returns record present → CONTRADICTED
  E-06: refund_issued_item_not_returned — no returns record → SILENT
  E-07: duplicate charge — same unit/type/amount within 7 days
  E-08: inbound_defect_fee — uncertain prep fields → UNCERTAIN
  E-09: damaged_in_warehouse — no upstream → SILENT
  E-10: fulfilment_fee_weight_tier — SKU confirmed only → UNCERTAIN
  E-11: inbound_defect_fee — SLA expired → SILENT (would be CONTRADICTED otherwise)
  E-12: lost_inbound — already has inventory_adjustment + clean receiving → CONTRADICTED
"""

# ── Fee report CSV ─────────────────────────────────────────────────────────
EVAL_FEE_CSV = """line_id,report_type,unit_id,org_id,sku,fnsku,fba_shipment_id,order_id,charge_type,quantity,amount_usd,posted_date
E-01,fee_report,EVAL-U001,org_demo_alpha,SKU-CABLE-USBC,X00EVAL001,FBA-EVAL-1,,inbound_defect_fee,1,2.50,2026-09-10
E-02,fee_report,EVAL-U002,org_demo_alpha,SKU-PUZZLE-500,X00EVAL002,FBA-EVAL-1,,inbound_defect_fee,1,1.50,2026-09-12
E-03,inventory_adjustment,EVAL-U003,org_demo_alpha,SKU-LAMP-LED,X00EVAL003,FBA-EVAL-1,,lost_inbound,1,0.00,2026-09-01
E-04,inventory_adjustment,EVAL-U004,org_demo_alpha,SKU-BOTTLE-750,X00EVAL004,FBA-EVAL-1,,lost_inbound,1,0.00,2026-09-01
E-05,fee_report,EVAL-U005,org_demo_alpha,SKU-LEASH-6FT,X00EVAL005,FBA-EVAL-2,ORD-EVAL-5001,refund_issued_item_not_returned,1,0.00,2026-08-01
E-06,fee_report,EVAL-U006,org_demo_alpha,SKU-MUG-11,X00EVAL006,FBA-EVAL-2,ORD-EVAL-5002,refund_issued_item_not_returned,1,0.00,2026-08-01
E-07A,fee_report,EVAL-U007,org_demo_alpha,SKU-CANDLE-3,X00EVAL007,FBA-EVAL-2,,inbound_defect_fee,1,3.00,2026-09-15
E-07B,fee_report,EVAL-U007,org_demo_alpha,SKU-CANDLE-3,X00EVAL007,FBA-EVAL-2,,inbound_defect_fee,1,3.00,2026-09-18
E-08,fee_report,EVAL-U008,org_demo_alpha,SKU-SERUM-30,X00EVAL008,FBA-EVAL-3,,inbound_defect_fee,1,1.00,2026-09-20
E-09,fee_report,EVAL-U009,org_demo_alpha,SKU-TOWEL-BLU,X00EVAL009,FBA-EVAL-3,,damaged_in_warehouse,1,12.00,2026-09-05
E-10,fee_report,EVAL-U010,org_demo_alpha,SKU-PROT-1KG,X00EVAL010,FBA-EVAL-3,ORD-EVAL-5010,fulfilment_fee_weight_tier,1,5.10,2026-09-22
E-11,fee_report,EVAL-U011,org_demo_alpha,SKU-CABLE-USBC,X00EVAL011,FBA-EVAL-4,,inbound_defect_fee,1,2.00,2026-06-01
E-12,inventory_adjustment,EVAL-U012,org_demo_alpha,SKU-MUG-11,X00EVAL012,FBA-EVAL-4,,lost_inbound,1,0.00,2026-09-10
"""

# ── Receiving CSV ──────────────────────────────────────────────────────────
EVAL_RECEIVING_CSV = """record_id,unit_id,org_id,po_number,po_line,supplier,sku,asin,product_title,spec_colour,spec_variant,spec_components,cartons_ordered,cartons_received,units_per_carton_ordered,units_per_carton_counted,qty_ordered,qty_received,identity_match,carton_damage,unit_damage,quality_flags,photo_refs,operator_id,captured_at
ERCV-001,EVAL-U001,org_demo_alpha,PO-EVAL-1,1,Supplier A,SKU-CABLE-USBC,B0EVAL001,USB-C Cable,white,2m,cable,2,2,12,12,24,24,yes,none,none,,fixtures/eval/r1.jpg,op_test,2026-08-15T10:00:00Z
ERCV-002,EVAL-U002,org_demo_alpha,PO-EVAL-1,2,Supplier A,SKU-PUZZLE-500,B0EVAL002,Jigsaw Puzzle,n/a,500pc,puzzle;poster,2,2,12,12,24,24,yes,none,none,,fixtures/eval/r2.jpg,op_test,2026-08-15T11:00:00Z
ERCV-003,EVAL-U003,org_demo_alpha,PO-EVAL-2,1,Supplier B,SKU-LAMP-LED,B0EVAL003,LED Lamp,grey,standard,lamp;cable;manual,1,1,6,6,6,6,yes,none,none,,fixtures/eval/r3.jpg,op_test,2026-08-16T09:00:00Z
ERCV-004,EVAL-U004,org_demo_alpha,PO-EVAL-2,2,Supplier B,SKU-BOTTLE-750,B0EVAL004,Water Bottle,black,750ml,bottle;lid,2,1,6,6,12,6,yes,none,none,,fixtures/eval/r4.jpg,op_test,2026-08-16T10:00:00Z
ERCV-010,EVAL-U010,org_demo_alpha,PO-EVAL-3,1,Supplier C,SKU-PROT-1KG,B0EVAL010,Whey Protein,n/a,1kg,tub;scoop,1,1,12,12,12,12,yes,none,none,,fixtures/eval/r10.jpg,op_test,2026-08-20T08:00:00Z
ERCV-011,EVAL-U011,org_demo_alpha,PO-EVAL-4,1,Supplier D,SKU-CABLE-USBC,B0EVAL011,USB-C Cable,white,2m,cable,1,1,12,12,12,12,yes,none,none,,fixtures/eval/r11.jpg,op_test,2026-05-01T08:00:00Z
ERCV-012,EVAL-U012,org_demo_alpha,PO-EVAL-4,2,Supplier D,SKU-MUG-11,B0EVAL012,Ceramic Mug,white,11oz,mug x2,2,2,12,12,24,24,yes,none,none,,fixtures/eval/r12.jpg,op_test,2026-08-25T08:00:00Z
"""

# ── Prep CSV ───────────────────────────────────────────────────────────────
EVAL_PREP_CSV = """record_id,unit_id,org_id,work_order_id,fba_shipment_id,sku,asin,fnsku,prep_price_usd,wo_polybag,wo_suffocation_warning,wo_expiry_date,wo_handling_marks,polybag_present_sealed,suffocation_warning,fnsku_label_placement,original_barcode_covered,expiry_date,handling_marks,photo_refs,operator_id,captured_at
EPRP-001,EVAL-U001,org_demo_alpha,WO-EVAL-1,FBA-EVAL-1,SKU-CABLE-USBC,B0EVAL001,X00EVAL001,0.40,True,True,False,,yes,legible,flat,yes,not_required,not_required,fixtures/eval/p1.jpg,op_test,2026-08-20T10:00:00Z
EPRP-002,EVAL-U002,org_demo_alpha,WO-EVAL-1,FBA-EVAL-1,SKU-PUZZLE-500,B0EVAL002,X00EVAL002,0.90,True,True,False,,yes,legible,on_seam,yes,not_required,not_required,fixtures/eval/p2.jpg,op_test,2026-08-20T11:00:00Z
EPRP-007A,EVAL-U007,org_demo_alpha,WO-EVAL-2,FBA-EVAL-2,SKU-CANDLE-3,B0EVAL007,X00EVAL007,0.40,False,False,False,fragile,not_required,not_required,flat,yes,not_required,all_present,fixtures/eval/p7.jpg,op_test,2026-09-01T09:00:00Z
EPRP-008,EVAL-U008,org_demo_alpha,WO-EVAL-3,FBA-EVAL-3,SKU-SERUM-30,B0EVAL008,X00EVAL008,0.55,True,True,True,liquid,uncertain,uncertain,uncertain,uncertain,uncertain,uncertain,fixtures/eval/p8.jpg,op_test,2026-09-05T10:00:00Z
EPRP-010,EVAL-U010,org_demo_alpha,WO-EVAL-3,FBA-EVAL-3,SKU-PROT-1KG,B0EVAL010,X00EVAL010,1.10,False,False,True,,not_required,not_required,flat,yes,legible,not_required,fixtures/eval/p10.jpg,op_test,2026-09-10T08:00:00Z
EPRP-011,EVAL-U011,org_demo_alpha,WO-EVAL-4,FBA-EVAL-4,SKU-CABLE-USBC,B0EVAL011,X00EVAL011,0.40,True,True,False,,yes,legible,flat,yes,not_required,not_required,fixtures/eval/p11.jpg,op_test,2026-04-15T08:00:00Z
EPRP-012,EVAL-U012,org_demo_alpha,WO-EVAL-4,FBA-EVAL-4,SKU-MUG-11,B0EVAL012,X00EVAL012,0.40,False,False,False,fragile,not_required,not_required,flat,yes,not_required,all_present,fixtures/eval/p12.jpg,op_test,2026-08-20T08:00:00Z
"""

# ── Returns CSV ────────────────────────────────────────────────────────────
EVAL_RETURNS_CSV = """record_id,unit_id,org_id,order_id,ordered_sku,ordered_asin,identity_match,parts_list,parts_missing,observed_state,amazon_condition,operator_disposition,photo_refs,operator_id,captured_at
ERTN-005,EVAL-U005,org_demo_alpha,ORD-EVAL-5001,SKU-LEASH-6FT,B0EVAL005,yes,leash,,factory_sealed,,restock,fixtures/eval/rtn5.jpg,op_test,2026-08-25T10:00:00Z
"""

# ── Ground Truth ───────────────────────────────────────────────────────────
# Planted by the builder; known before the model runs.
GROUND_TRUTH: dict[str, dict] = {
    "E-01": {
        "expected_verdict": "CONTRADICTED",
        "note": "Prep all-pass; clean FNSKU, polybag, suffocation — should contradict inbound_defect_fee",
    },
    "E-02": {
        "expected_verdict": "SUPPORTED",
        "note": "fnsku_label_placement=on_seam is a defect; fee is legitimate",
    },
    "E-03": {
        "expected_verdict": "CONTRADICTED",
        "note": "Receiving qty_received=6 matches qty_ordered=6; lost_inbound claim disputable",
    },
    "E-04": {
        "expected_verdict": "SUPPORTED",
        "note": "Receiving qty_received=6 < qty_ordered=12; short ship; loss confirmed",
    },
    "E-05": {
        "expected_verdict": "CONTRADICTED",
        "note": "Returns record shows unit was received back (restock); contradicts 'not returned'",
    },
    "E-06": {
        "expected_verdict": "SILENT",
        "note": "No returns record for EVAL-U006; cannot contradict 'item not returned'",
    },
    "E-07A": {
        "expected_verdict": "CONTRADICTED",
        "note": "Prep passes; plus duplicate flag with E-07B (same unit/amount/type within 7 days)",
    },
    "E-07B": {
        "expected_verdict": "CONTRADICTED",
        "note": "Duplicate of E-07A; duplicate_flag should be set",
    },
    "E-08": {
        "expected_verdict": "UNCERTAIN",
        "note": "All prep fields are 'uncertain'; evidence ambiguous → UNCERTAIN",
    },
    "E-09": {
        "expected_verdict": "SILENT",
        "note": "No upstream records for EVAL-U009; cannot support damaged_in_warehouse claim",
    },
    "E-10": {
        "expected_verdict": "UNCERTAIN",
        "note": "SKU confirmed but cannot verify actual weight tier from records alone",
    },
    "E-11": {
        "expected_verdict": "SILENT",
        "note": "Posted 2026-06-01; inbound_defect_fee window is 60 days; deadline ~2026-07-31; expired",
    },
    "E-12": {
        "expected_verdict": "CONTRADICTED",
        "note": "Receiving shows full qty received; lost_inbound claim disputable",
    },
}
