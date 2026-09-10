REPORT zmm_pr_approve.
* 구매요청 승인 리포트

TABLES zorder_hdr.

PARAMETERS p_ordid TYPE zde_order_id OBLIGATORY.

START-OF-SELECTION.

  AUTHORITY-CHECK OBJECT 'Z_ORDER'
    ID 'ACTVT' FIELD '02'.
  IF sy-subrc <> 0.
    MESSAGE e002(zmm_msg).
  ENDIF.

  DATA(lo_service) = NEW zcl_order_service( ).
  DATA(ls_order)   = lo_service->read_order( p_ordid ).

  IF lo_service->zif_order_handler~validate( p_ordid ) = abap_true.
    lo_service->zif_order_handler~post( ls_order ).
    MESSAGE s003(zmm_msg).
  ENDIF.

  SUBMIT zmm_pr_print WITH p_ordid = p_ordid AND RETURN.
