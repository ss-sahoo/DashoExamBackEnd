
@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def update_batch(request, batch_id):
    """
    Update a batch.
    - Admin (own center) or Super Admin.
    """
    user = request.user
    
    try:
        batch = Batch.objects.get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Permission check
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center or batch.center != user.center:
            return Response(
                {"detail": "You don't have permission to update this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Admin and Super Admin can update batches."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Fields to update
    name = request.data.get("name")
    start_date_str = request.data.get("start_date")
    end_date_str = request.data.get("end_date")
    program_id = request.data.get("program_id")

    if name:
        batch.name = name

    if start_date_str:
        try:
            batch.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "start_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    if end_date_str:
        try:
            batch.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "end_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if program_id:
        try:
            program = Program.objects.get(id=program_id)
            # Ensure program belongs to same institute
            if batch.center and program.institute != batch.center.institute:
                 return Response(
                    {"detail": "Program does not belong to the same institute as the batch."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            batch.program = program
        except Program.DoesNotExist:
             return Response(
                {"detail": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    batch.save()

    return Response(
        {
            "id": str(batch.id),
            "name": batch.name,
            "start_date": str(batch.start_date) if batch.start_date else None,
            "end_date": str(batch.end_date) if batch.end_date else None,
            "program_id": str(batch.program.id) if batch.program else None,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_batch(request, batch_id):
    """
    Delete a batch.
    """
    user = request.user
    
    try:
        batch = Batch.objects.get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Permission check
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center or batch.center != user.center:
            return Response(
                {"detail": "You don't have permission to delete this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Admin and Super Admin can delete batches."},
            status=status.HTTP_403_FORBIDDEN,
        )

    batch.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
