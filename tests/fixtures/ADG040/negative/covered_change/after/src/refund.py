def refund(order):
    if order.is_gift:
        return issue_voucher(order)
    return reverse_charge(order)
