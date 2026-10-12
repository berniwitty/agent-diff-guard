def refund(order):
    if order.is_gift:
        voucher = issue_voucher(order)
        return voucher
    return reverse_charge(order)
