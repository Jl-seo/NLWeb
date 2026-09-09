REPORT zmm_pr_print.
PARAMETERS p_ordid TYPE zde_order_id.

START-OF-SELECTION.
  SELECT * FROM zorder_hdr INTO TABLE @DATA(lt_order)
    WHERE order_id = @p_ordid.

  CALL FUNCTION 'SSF_FUNCTION_MODULE_NAME'
    EXPORTING
      formname = 'ZSF_ORDER'.
