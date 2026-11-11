! GNU Fortran compatibility shim for building the GEAR1 source without Intel MKL.
! This uses the compiler's intrinsic RNG and is NOT the Intel MKL VSL MCG31 stream.
module mkl_vsl
  implicit none
  integer, parameter :: VSL_BRNG_MCG31 = 1
  integer, parameter :: VSL_STATUS_OK = 0
  integer, parameter :: VSL_RNG_METHOD_GAUSSIAN_BOXMULLER = 0
  type :: VSL_STREAM_STATE
    integer :: seed = 1
  end type VSL_STREAM_STATE
contains
  integer function VslNewStream(stream, brng, seed)
    type(VSL_STREAM_STATE), intent(out) :: stream
    integer, intent(in) :: brng, seed
    integer :: n, i
    integer, allocatable :: seed_array(:)
    call random_seed(size=n)
    allocate(seed_array(n))
    do i=1,n
      seed_array(i) = seed + 37*i
    end do
    call random_seed(put=seed_array)
    stream%seed = seed
    VslNewStream = VSL_STATUS_OK
  end function VslNewStream

  integer function vsRngUniform(method, stream, n, r, a, b)
    integer, intent(in) :: method, n
    type(VSL_STREAM_STATE), intent(inout) :: stream
    real, intent(out) :: r(*)
    real, intent(in) :: a, b
    integer :: i
    real :: u
    do i=1,n
      call random_number(u)
      r(i) = a + (b-a)*u
    end do
    vsRngUniform = VSL_STATUS_OK
  end function vsRngUniform

  integer function vsRngGaussian(method, stream, n, r, a, sigma)
    integer, intent(in) :: method, n
    type(VSL_STREAM_STATE), intent(inout) :: stream
    real, intent(out) :: r(*)
    real, intent(in) :: a, sigma
    integer :: i
    real :: u1, u2, z
    do i=1,n
      call random_number(u1)
      call random_number(u2)
      u1 = max(u1, tiny(u1))
      z = sqrt(-2.0*log(u1))*cos(6.2831853071795864769*u2)
      r(i) = a + sigma*z
    end do
    vsRngGaussian = VSL_STATUS_OK
  end function vsRngGaussian
end module mkl_vsl
